# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Clang toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/cipd',
  'infra/fuchsia',
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
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

TARGETS = [
  ('aarch64', 'arm64'),
  ('x86_64', 'x64'),
]

LLVM_PROJECT_GIT = 'https://fuchsia.googlesource.com/third_party/llvm-project'

PROPERTIES = {
  'url': Property(kind=str, help='Git repository URL', default=LLVM_PROJECT_GIT),
  'ref': Property(kind=str, help='Git reference', default='refs/heads/master'),
  'revision': Property(kind=str, help='Revision', default=None),
}


def RunSteps(api, url, ref, revision):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()

  if not revision:
    revision = api.gitiles.refs(url).get(ref, None)
  cipd_pkg_name = 'fuchsia/clang/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      packages = {
        'infra/cmake/${platform}': 'version:3.9.2',
        'infra/ninja/${platform}': 'version:1.8.2',
        'fuchsia/clang/${platform}': 'goma',
      }
      if api.platform.name == 'linux':
        packages.update({
          'fuchsia/sysroot/${platform}': 'latest'
        })
      api.cipd.ensure(cipd_dir, packages)

  staging_dir = api.path.mkdtemp('clang')
  pkg_name = 'clang-%s' % api.platform.name.replace('mac', 'darwin')
  pkg_dir = staging_dir.join(pkg_name)
  api.file.ensure_directory('create pkg dir', pkg_dir)

  api.fuchsia.checkout(
      manifest='manifest/garnet',
      remote='https://fuchsia.googlesource.com/garnet',
      project='garnet',
  )

  with api.context(infra_steps=True):
    llvm_dir = api.path['start_dir'].join('llvm-project')
    api.git.checkout(url, llvm_dir, ref=revision, submodules=True)

  sdk_dir = staging_dir.join('sdk')
  api.file.ensure_directory('create sdk dir', sdk_dir)

  # Build Zircon sysroot.
  # TODO(mcgrathr): Move this into a module shared by all *_toolchain.py.
  overlay = False
  for tc_arch, gn_arch in TARGETS:
    build = api.fuchsia.build(
        target=gn_arch,
        build_type='release',
        packages=['garnet/packages/sdk/garnet'],
    )
    api.python('create %s sdk' % gn_arch,
        api.path['start_dir'].join('scripts', 'sdk', 'create_layout.py'),
        args=[
          '--manifest',
          build.fuchsia_build_dir.join('gen', 'garnet', 'public', 'sdk', 'garnet_molecule.sdk'),
          '--output',
          sdk_dir,
        ] + (['--overlay'] if overlay else []),
    )
    overlay = True

  # build clang+llvm
  build_dir = staging_dir.join('llvm_build_dir')
  api.file.ensure_directory('create llvm build dir', build_dir)

  extra_options = {
    'linux': [
      '-DBOOTSTRAP_CMAKE_EXE_LINKER_FLAGS=-static-libstdc++',
      '-DBOOTSTRAP_CMAKE_SYSROOT=%s' % cipd_dir,
      '-DCMAKE_SYSROOT=%s' % cipd_dir,
    ],
    'mac': [],
  }[api.platform.name]

  extra_options = []
  for tc_arch, gn_arch in TARGETS:
    extra_options.extend([
      '-DSTAGE2_FUCHSIA_%s_SYSROOT=-I%s' % (tc_arch, sdk_dir.join('arch', gn_arch, 'sysroot')),
      '-DSTAGE2_FUCHSIA_%s_C_FLAGS=-I%s' % (tc_arch, sdk_dir.join('pkg', 'launchpad', 'include')),
      '-DSTAGE2_FUCHSIA_%s_CXX_FLAGS=-I%s' % (tc_arch, sdk_dir.join('pkg', 'launchpad', 'include')),
      '-DSTAGE2_FUCHSIA_%s_LINKER_FLAGS=-L%s' % (tc_arch, sdk_dir.join('arch', gn_arch, 'lib')),
    ])

  with api.goma.build_with_goma(), api.context(cwd=build_dir):
    api.step('configure clang', [
      cipd_dir.join('bin', 'cmake'),
      '-GNinja',
      '-DCMAKE_C_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
      '-DCMAKE_CXX_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
      '-DCMAKE_ASM_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
      '-DCMAKE_C_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
      '-DCMAKE_CXX_COMPILER=%s' % cipd_dir.join('bin', 'clang++'),
      '-DCMAKE_ASM_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
      '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
      '-DCMAKE_INSTALL_PREFIX=',
      '-DLLVM_ENABLE_PROJECTS=clang;lld',
      '-DLLVM_ENABLE_RUNTIMES=compiler-rt;libcxx;libcxxabi;libunwind',
    ] + extra_options + [
      '-C', llvm_dir.join('clang', 'cmake', 'caches', 'Fuchsia.cmake'),
      llvm_dir.join('llvm'),
    ])
    api.step('build clang', [cipd_dir.join('ninja'), 'stage2-distribution'])
    # TODO: we should be running stage2-check-all
    api.step('check llvm', [cipd_dir.join('ninja'), 'stage2-check-llvm'])
    api.step('check clang', [cipd_dir.join('ninja'), 'stage2-check-clang'])
    with api.context(env={'DESTDIR': pkg_dir}):
      api.step('install clang',
               [cipd_dir.join('ninja'), 'stage2-install-distribution'])

  # use first rather than second stage clang just in case we're cross-compiling
  step_result = api.step('clang version',
      [build_dir.join('bin', 'clang'), '--version'],
      stdout=api.raw_io.output())
  m = re.search(r'version ([0-9.-]+)', step_result.stdout)
  assert m, 'Cannot determine Clang version'
  clang_version = m.group(1)

  # TODO(TO-471): Ideally this would be done by the cmake build itself.
  manifest_format = ''
  for soname in [
      'libclang_rt.asan-{arch}.so',
      'libclang_rt.ubsan_standalone-{arch}.so',
      'libclang_rt.scudo-{arch}.so',
  ]:
    manifest_format += ('lib/%s=clang/{clang_version}/lib/fuchsia/%s\n' %
                        (soname, soname))
  for prefix in ('', 'asan/'):
    for soname in [
        'libc++.so.2',
        'libc++abi.so.1',
        'libunwind.so.1',
    ]:
      manifest_format += ('lib/%s={arch}-fuchsia/lib/%s\n' %
                         (prefix + soname, prefix + soname))
  for tc_arch, gn_arch in TARGETS:
    manifest_file = '%s-fuchsia.manifest' % tc_arch
    api.file.write_text('write %s' % manifest_file,
                        pkg_dir.join('lib', manifest_file),
                        manifest_format.format(arch=tc_arch,
                                               clang_version=clang_version))

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=pkg_dir,
      install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/clang.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('clang.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': clang_version,
        'git_repository': LLVM_PROJECT_GIT,
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('clang', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  version = 'clang version 5.0.0 (trunk 302207) (llvm/trunk 302209)'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.step_data('clang version', api.raw_io.stream_output(version)) +
           api.step_data('cipd search fuchsia/clang/' + platform + '-amd64 ' +
                         'git_revision:' + revision,
                         api.json.output({'result': []})))
