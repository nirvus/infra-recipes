# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building GCC toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/gsutil',
  'infra/hash',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
  'recipe_engine/url',
]

BINUTILS_GIT = 'https://gnu.googlesource.com/binutils-gdb'
BINUTILS_REF = 'refs/tags/binutils-2_28'

GCC_GIT = 'https://gnu.googlesource.com/gcc'
GCC_REF = 'refs/heads/roland/6.3.0/pr77609'

PROPERTIES = {
  'revision': Property(kind=str, help='Revision', default=None),
}


def RunSteps(api, revision):
  api.gitiles.ensure_gitiles()
  api.gsutil.ensure_gsutil()

  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  if not revision:
    revision = api.gitiles.refs(GCC_GIT, refspath='refs').get(GCC_REF, None)
  cipd_pkg_name = 'fuchsia/gcc/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      packages = {
        'fuchsia/clang/${platform}': 'latest',
      }
      if api.platform.name == 'linux':
        packages.update({
          'fuchsia/sysroot/${platform}': 'latest'
        })
      api.cipd.ensure(cipd_dir, packages)

  with api.context(infra_steps=True):
    binutils_dir = api.path['start_dir'].join('binutils-gdb')
    api.git.checkout(BINUTILS_GIT, binutils_dir, ref=BINUTILS_REF)
    gcc_dir = api.path['start_dir'].join('gcc')
    api.git.checkout(GCC_GIT, gcc_dir, ref=GCC_REF)

  with api.context(cwd=gcc_dir):
    # download GCC dependencies: GMP, ISL, MPC and MPFR libraries
    api.step('download prerequisites', [
      gcc_dir.join('contrib', 'download_prerequisites')
    ])

  staging_dir = api.path.mkdtemp('gcc')
  pkg_name = 'gcc-%s' % api.platform.name.replace('mac', 'darwin')
  pkg_dir = staging_dir.join(pkg_name)
  api.file.ensure_directory('create pkg dir', pkg_dir)

  extra_args = []
  if api.platform.name == 'linux':
    extra_args = ['--with-build-sysroot=%s' % cipd_dir]

  extra_env = {}
  if api.platform.name == 'mac':
    # needed to work around problem with clang compiler and some generated code in gcc
    extra_env['CFLAGS'] = '-fbracket-depth=1024 -g -O2'
    extra_env['CXXFLAGS'] = '-fbracket-depth=1024 -g -O2'

  for target in ['aarch64', 'x86_64']:
    # build binutils
    binutils_build_dir = staging_dir.join('binutils_%s_build_dir' % target)
    api.file.ensure_directory('create binutils %s build dir' % target, binutils_build_dir)

    with api.context(cwd=binutils_build_dir):
      api.step('configure binutils', [
        binutils_dir.join('configure'),
        '--prefix=', # we're building a relocatable package
        '--target=%s-elf' % target,
        '--enable-initfini-array', # Fuchsia uses .init/.fini arrays
        '--enable-deterministic-archives', # more deterministic builds
        '--enable-gold', # Zircon uses gold for userspace build
        '--disable-werror', # ignore warnings reported by Clang
        '--disable-nls', # no need for locatization
        '--with-included-gettext', # use include gettext library
      ] + extra_args + {
        'aarch64': ['--enable-targets=arm-eabi'],
        'x86_64': ['--enable-targets=x86_64-pep'],
      }[target])
      api.step('build binutils', [
        'make',
        '-j%s' % api.platform.cpu_count,
        'all-binutils', 'all-gas', 'all-ld', 'all-gold',
      ])
      with api.context(env={'DESTDIR': pkg_dir}):
        api.step('install binutils', [
          'make',
          'install-strip-binutils',
          'install-strip-gas',
          'install-strip-ld',
          'install-strip-gold',
        ])

    # build gcc
    gcc_build_dir = staging_dir.join('gcc_%s_build_dir' % target)
    api.file.ensure_directory('create gcc %s build dir' % target, gcc_build_dir)

    with api.context(cwd=gcc_build_dir, env=extra_env,
                     env_prefixes={'PATH': [pkg_dir.join('bin')]}):
      api.step('configure gcc', [
        gcc_dir.join('configure'),
        '--prefix=', # we're building a relocatable package
        '--target=%s-elf' % target,
        '--enable-languages=c,c++',
        '--enable-initfini-array', # Fuchsia uses .init/.fini arrays
        '--enable-gold', # Zircon uses gold for userspace build
        '--disable-werror', # ignore warnings reported by Clang
        '--disable-libstdcxx', # we don't need libstdc++
        '--disable-libssp', # we don't need libssp either
        '--disable-libquadmath', # and neither we need libquadmath
        '--with-included-gettext', # use included gettext library
      ] + extra_args)
      api.step('build gcc', [
        'make',
        '-j%s' % api.platform.cpu_count,
        'all-gcc', 'all-target-libgcc',
      ])
      with api.context(env={'DESTDIR': pkg_dir}):
        api.step('install gcc', [
          'make',
          'install-strip-gcc',
          'install-strip-target-libgcc',
        ])

  gcc_version = api.file.read_text('gcc version', gcc_dir.join('gcc', 'BASE-VER'))

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=pkg_dir,
      install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/gcc.cipd_version')

  cipd_pkg_file = api.path['tmp_base'].join('gcc.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': gcc_version,
        'git_repository': GCC_GIT,
        'git_revision': revision,
      },
  )

  instance_id = step_result.json.output['result']['instance_id']
  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('gcc', api.cipd.platform_suffix(), instance_id),
      unauthenticated_url=True
  )


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', (GCC_REF, revision)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', (GCC_REF, revision)) +
           api.step_data('gcc version', api.file.read_text('7.1.2')) +
           api.step_data('cipd search fuchsia/gcc/' + platform + '-amd64 ' +
                         'git_revision:' + revision,
                         api.json.output({'result': []})))
