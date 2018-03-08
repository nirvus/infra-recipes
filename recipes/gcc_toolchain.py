# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building GCC toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property, StepFailure

import re


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/goma',
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
BINUTILS_REF = 'refs/tags/binutils-2_30'

GCC_GIT = 'https://gnu.googlesource.com/gcc'
GCC_REF = 'refs/heads/roland/6.3.0/zircon'

PROPERTIES = {
  'binutils_revision': Property(kind=str, help='Revision in binutils repo',
                                default=None),
  'gcc_revision': Property(kind=str, help='Revision in GCC repo', default=None),
}


def RunSteps(api, binutils_revision, gcc_revision):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()
  api.gsutil.ensure_gsutil()

  if binutils_revision is None:
    binutils_revision = api.gitiles.refs(
        BINUTILS_GIT, step_name='binutils refs').get(BINUTILS_REF, None)
  if gcc_revision is None:
    gcc_revision = api.gitiles.refs(
        GCC_GIT, step_name='gcc refs').get(GCC_REF, None)

  cipd_pkg_name = 'fuchsia/gcc/' + api.cipd.platform_suffix()
  cipd_git_revision = ','.join([gcc_revision, binutils_revision])

  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + cipd_git_revision)
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
    api.git.checkout(BINUTILS_GIT, binutils_dir, ref=binutils_revision)
    gcc_dir = api.path['start_dir'].join('gcc')
    api.git.checkout(GCC_GIT, gcc_dir, ref=gcc_revision)

  with api.context(cwd=gcc_dir):
    # download GCC dependencies: GMP, ISL, MPC and MPFR libraries
    api.step('download prerequisites', [
      gcc_dir.join('contrib', 'download_prerequisites')
    ])

  staging_dir = api.path.mkdtemp('gcc')
  pkg_name = 'gcc-%s' % api.platform.name.replace('mac', 'darwin')
  pkg_dir = staging_dir.join(pkg_name)
  api.file.ensure_directory('create pkg dir', pkg_dir)

  host_clang = '%s %s' % (api.goma.goma_dir.join('gomacc'),
                          cipd_dir.join('bin', 'clang'))
  host_cflags = '-flto -O3'
  host_compiler_args = {
      'CC': host_clang,
      'CXX': '%s++' % host_clang,
      'CFLAGS': host_cflags,
      'CXXFLAGS': '%s -static-libstdc++' % host_cflags,
  }

  extra_args = []
  if api.platform.name == 'linux':
    host_compiler_args['--with-build-sysroot'] = cipd_dir
    extra_args.append('--with-build-sysroot=%s' % cipd_dir)

  if api.platform.name == 'mac':
    # Needed to work around problem with clang compiler and some generated
    # code in gcc.
    extra_args += ['%s=-fbracket-depth=1024 -g -O2' % flagvar
                   for flagvar in ('CFLAGS', 'CXXFLAGS')]

  host_compiler_args = sorted('%s=%s' % item
                              for item in host_compiler_args.iteritems())

  with api.goma.build_with_goma():
    for target, enable_targets in [('aarch64', 'arm-eabi'),
                                   ('x86_64', 'x86_64-pep')]:
      # configure arguments that are the same for binutils and gcc.
      common_args = [
          '--prefix=', # we're building a relocatable package
          '--target=%s-elf' % target,
          '--enable-initfini-array', # Fuchsia uses .init/.fini arrays
          '--enable-gold', # Zircon uses gold for userspace build
          '--disable-werror', # ignore warnings reported by Clang
          '--disable-nls', # no need for locatization
          '--with-included-gettext', # use include gettext library
      ]

      # build binutils
      binutils_build_dir = staging_dir.join('binutils_%s_build_dir' % target)
      api.file.ensure_directory('create binutils %s build dir' % target,
                                binutils_build_dir)

      with api.context(cwd=binutils_build_dir):
        def binutils_make_step(name, prefix, jobs, make_args=[], logs=[]):
          return api.step('%s %s binutils' % (name, target),
                          ['make','-j%s' % jobs] + make_args +
                          ['%s-%s' % (prefix, component)
                           for component in ['binutils', 'gas', 'ld', 'gold']])
        api.step('configure %s binutils' % target, [
          binutils_dir.join('configure'),
          '--enable-deterministic-archives', # more deterministic builds
          '--enable-targets=%s' % enable_targets,
        ] + common_args + host_compiler_args)
        binutils_make_step('build', 'all', api.goma.recommended_goma_jobs)
        try:
          binutils_make_step('test', 'check', api.platform.cpu_count,['-k'])
        except StepFailure as error: # pragma: no cover
          for log in [
              ('gas', 'testsuite', 'gas.log'),
              ('binutils', 'binutils.log'),
              ('ld', 'ld.log'),
              ('gold', 'testsuite', 'test-suite.log'),
          ]:
            error.result.presentation.logs[log[0]] = api.file.read_text(
                'binutils %s %s' % (target, '/'.join(log)),
                binutils_build_dir.join(*log))
        binutils_make_step('install', 'install-strip', 1,
                           ['DESTDIR=%s' % pkg_dir])

      # build gcc
      gcc_build_dir = staging_dir.join('gcc_%s_build_dir' % target)
      api.file.ensure_directory('create gcc %s build dir' % target,
                                gcc_build_dir)

      with api.context(cwd=gcc_build_dir,
                       env_prefixes={'PATH': [pkg_dir.join('bin')]}):
        api.step('configure %s gcc' % target, [
          gcc_dir.join('configure'),
          '--enable-languages=c,c++',
          '--disable-libstdcxx', # we don't need libstdc++
          '--disable-libssp', # we don't need libssp either
          '--disable-libquadmath', # and neither we need libquadmath
        ] + common_args + extra_args)
        api.step('build %s gcc' % target, [
          'make',
          '-j%s' % api.platform.cpu_count,
          'all-gcc', 'all-target-libgcc',
        ])
        api.step('install %s gcc' % target, [
          'make',
          'DESTDIR=%s' % pkg_dir,
          'install-strip-gcc',
          'install-strip-target-libgcc',
        ])

  binutils_version = api.file.read_text('binutils version',
                                        binutils_dir.join('bfd', 'version.m4'))
  m = re.match(r'm4_define\(\[BFD_VERSION\], \[([^]]+)\]\)', binutils_version)
  assert m and m.group(1), 'bfd/version.m4 has unexpected format'
  binutils_version = m.group(1)
  gcc_version = api.file.read_text('gcc version',
                                   gcc_dir.join('gcc', 'BASE-VER')).rstrip()

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
        'version': ','.join([gcc_version, binutils_version]),
        'git_repository': ','.join([GCC_GIT, BINUTILS_GIT]),
        'git_revision': cipd_git_revision,
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
  binutils_revision = '3d861fdb826c2f5cf270dd5f585d0e6057e1bf4f'
  gcc_revision = '4b5e15daff8b54440e3fda451c318ad31e532fab'
  cipd_revision = ','.join([gcc_revision, binutils_revision])
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('binutils refs',
                            (BINUTILS_REF, binutils_revision)) +
           api.gitiles.refs('gcc refs',
                            (GCC_REF, gcc_revision)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('binutils refs',
                            (BINUTILS_REF, binutils_revision)) +
           api.gitiles.refs('gcc refs',
                            (GCC_REF, gcc_revision)) +
           api.step_data('binutils version', api.file.read_text(
               'm4_define([BFD_VERSION], [2.27.0])')) +
           api.step_data('gcc version', api.file.read_text('7.1.2\n')) +
           api.step_data('cipd search fuchsia/gcc/' + platform + '-amd64 ' +
                         'git_revision:' + cipd_revision,
                         api.json.output({'result': []})))
