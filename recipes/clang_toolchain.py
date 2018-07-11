# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Clang toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/git',
  'infra/gitiles',
  'infra/goma',
  'infra/gsutil',
  'recipe_engine/cipd',
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

TARGET_TO_ARCH = {
  'x64': 'x86_64',
  'arm64': 'aarch64',
}
TARGETS = TARGET_TO_ARCH.keys()

PLATFORM_TO_TRIPLE = {
  'linux-amd64': 'x86_64-linux-gnu',
  'linux-arm64': 'aarch64-linux-gnu',
  'mac-amd64': 'x86_64-apple-darwin',
}
PLATFORMS = PLATFORM_TO_TRIPLE.keys()

LIBXML2_GIT = 'https://fuchsia.googlesource.com/third_party/libxml2'
ZLIB_GIT = 'https://fuchsia.googlesource.com/third_party/zlib'

PROPERTIES = {
  'repository':
      Property(
          kind=str, help='Git repository URL',
          default='https://fuchsia.googlesource.com/third_party/llvm-project'),
  'branch':
      Property(kind=str, help='Git branch', default='refs/heads/master'),
  'revision':
      Property(kind=str, help='Revision', default=None),
  'platform':
      Property(
          kind=str, help='CIPD platform for the target', default=None),
}


def RunSteps(api, repository, branch, revision, platform):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()
  api.gsutil.ensure_gsutil()

  if not revision:
    revision = api.gitiles.refs(repository).get(branch, None)

  # TODO: factor this out into a host_build recipe module.
  host_platform = '%s-%s' % (api.platform.name.replace('win', 'windows'), {
      'intel': {
          32: '386',
          64: 'amd64',
      },
      'arm': {
          32: 'armv6',
          64: 'arm64',
      },
  }[api.platform.arch][api.platform.bits])
  target_platform = platform or host_platform

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('infra/cmake/${platform}', 'version:3.9.2')
      pkgs.add_package('infra/ninja/${platform}', 'version:1.8.2')
      pkgs.add_package('fuchsia/clang/${platform}', 'goma')
      if api.platform.is_linux:
        pkgs.add_package('fuchsia/sysroot/linux-amd64', 'latest', 'linux-amd64')
        pkgs.add_package('fuchsia/sysroot/linux-arm64', 'latest', 'linux-arm64')
      pkgs.add_package('fuchsia/sdk/${platform}', 'latest', 'sdk')
      api.cipd.ensure(cipd_dir, pkgs)

  staging_dir = api.path.mkdtemp('clang')
  pkg_name = 'clang-%s' % api.platform.name.replace('mac', 'darwin')
  pkg_dir = staging_dir.join(pkg_name)
  api.file.ensure_directory('create pkg dir', pkg_dir)

  with api.context(infra_steps=True):
    llvm_dir = api.path['start_dir'].join('llvm-project')
    api.git.checkout(repository, llvm_dir, ref=revision, submodules=True)

  lib_install_dir = staging_dir.join('lib_install')
  api.file.ensure_directory('create lib_install_dir', lib_install_dir)

  target_triple = PLATFORM_TO_TRIPLE[target_platform]
  host_triple = PLATFORM_TO_TRIPLE[host_platform]

  if api.platform.name == 'linux':
    host_sysroot = cipd_dir.join(host_platform)
    target_sysroot = cipd_dir.join(target_platform)
  elif api.platform.name == 'mac':
    # TODO(IN-148): Eventually use our own hermetic sysroot as for Linux.
    step_result = api.step(
        'xcrun', ['xcrun', '--show-sdk-path'],
        stdout=api.raw_io.output(name='sdk-path', add_output_log=True),
        step_test_data=lambda: api.raw_io.test_api.stream_output(
            '/some/xcode/path'))
    target_sysroot = host_sysroot = step_result.stdout.strip()
  else: # pragma: no cover
    assert false, "unsupported platform"

  with api.goma.build_with_goma():
    vars = {
      'CC': '%s %s' % (api.goma.goma_dir.join('gomacc'), cipd_dir.join('bin', 'clang')),
      'CFLAGS': '-O3 -fPIC --target=%s --sysroot=%s' % (target_triple, target_sysroot),
      'AR': cipd_dir.join('bin', 'llvm-ar'),
      'NM': cipd_dir.join('bin', 'llvm-nm'),
      'RANLIB': cipd_dir.join('bin', 'llvm-ranlib'),
    }

    # build zlib
    with api.step.nest('zlib'):
      zlib_dir = api.path['start_dir'].join('zlib')
      api.git.checkout(ZLIB_GIT, zlib_dir, ref='refs/tags/v1.2.9', submodules=False)
      build_dir = staging_dir.join('zlib_build_dir')
      api.file.ensure_directory('create build dir', build_dir)
      with api.context(cwd=build_dir, env=vars):
        api.step('configure', [
          zlib_dir.join('configure'),
          '--prefix=',
          '--static',
        ])
        api.step('build', ['make', '-j%d' % api.goma.recommended_goma_jobs])
        api.step('install', ['make', 'install', 'DESTDIR=%s' % lib_install_dir])

    # build libxml2
    with api.step.nest('libxml2'):
      libxml2_dir = api.path['start_dir'].join('libxml2')
      api.git.checkout(LIBXML2_GIT, libxml2_dir, ref='refs/tags/v2.9.8', submodules=False)
      with api.context(cwd=libxml2_dir):
        api.step('autoconf', ['autoreconf', '-i', '-f'])
      build_dir = staging_dir.join('libxml2_build_dir')
      api.file.ensure_directory('create build dir', build_dir)
      with api.context(cwd=build_dir):
        api.step('configure', [
          libxml2_dir.join('configure'),
          '--prefix=',
          '--enable-static',
          '--disable-shared',
          '--with-zlib=%s' % lib_install_dir,
          '--without-icu',
          '--without-lzma',
          '--without-python',
        ] + ['%s=%s' % (k, v) for k, v in vars.iteritems()])
        api.step('build', ['make', '-j%d' % api.goma.recommended_goma_jobs])
        api.step('install', ['make', 'install', 'DESTDIR=%s' % lib_install_dir])

    # build clang+llvm
    build_dir = staging_dir.join('llvm_build_dir')
    api.file.ensure_directory('create llvm build dir', build_dir)

    extra_options = {
      'linux': [
        # Generic flags used by both stages.
        '-DCMAKE_AR=%s' % cipd_dir.join('bin', 'llvm-ar'),
        '-DCMAKE_LINKER=%s' % cipd_dir.join('bin', 'ld.lld'),
        '-DCMAKE_NM=%s' % cipd_dir.join('bin', 'llvm-nm'),
        '-DCMAKE_OBJCOPY=%s' % cipd_dir.join('bin', 'llvm-objcopy'),
        '-DCMAKE_OBJDUMP=%s' % cipd_dir.join('bin', 'llvm-objdump'),
        '-DCMAKE_RANLIB=%s' % cipd_dir.join('bin', 'llvm-ranlib'),
        '-DCMAKE_STRIP=%s' % cipd_dir.join('bin', 'llvm-strip'),
        # BOOTSTRAP_ prefixed flags are passed to the second stage compiler.
        '-DBOOTSTRAP_CMAKE_C_FLAGS=-I%s -I%s' % (lib_install_dir.join('include'), lib_install_dir.join('include', 'libxml2')),
        '-DBOOTSTRAP_CMAKE_CXX_FLAGS=-I%s -I%s' % (lib_install_dir.join('include'), lib_install_dir.join('include', 'libxml2')),
        '-DBOOTSTRAP_CMAKE_SHARED_LINKER_FLAGS=-static-libstdc++ -ldl -lpthread -L%s -L%s' % (cipd_dir.join(target_platform, 'lib'), lib_install_dir.join('lib')),
        '-DBOOTSTRAP_CMAKE_MODULE_LINKER_FLAGS=-static-libstdc++ -ldl -lpthread -L%s -L%s' % (cipd_dir.join(target_platform, 'lib'), lib_install_dir.join('lib')),
        '-DBOOTSTRAP_CMAKE_EXE_LINKER_FLAGS=-static-libstdc++ -ldl -lpthread -L%s -L%s' % (cipd_dir.join(target_platform, 'lib'), lib_install_dir.join('lib')),
        '-DBOOTSTRAP_CMAKE_SYSROOT=%s' % target_sysroot,
        '-DBOOTSTRAP_LLVM_DEFAULT_TARGET_TRIPLE=%s' % target_triple,
        # Unprefixed flags are only used by the first stage compiler.
        '-DCMAKE_EXE_LINKER_FLAGS=-static-libstdc++ -ldl -lpthread -L%s' % cipd_dir.join('lib'),
        '-DCMAKE_EXE_SHARED_FLAGS=-static-libstdc++ -ldl -lpthread -L%s' % cipd_dir.join('lib'),
        '-DCMAKE_SYSROOT=%s' % host_sysroot,
        '-DLLVM_DEFAULT_TARGET_TRIPLE=%s' % host_triple,
        '-DSTAGE2_LINUX_aarch64_SYSROOT=%s' % cipd_dir.join('linux-arm64'),
        '-DSTAGE2_LINUX_x86_64_SYSROOT=%s' % cipd_dir.join('linux-amd64'),
      ],
      'mac': [],
    }[api.platform.name]

    with api.step.nest('clang'), api.context(cwd=build_dir):
      api.step('configure', [
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
        '-DSTAGE2_FUCHSIA_SDK=%s' % cipd_dir.join('sdk'),
      ] + extra_options + [
        '-C', llvm_dir.join('clang', 'cmake', 'caches', 'Fuchsia.cmake'),
        llvm_dir.join('llvm'),
      ])
      api.step('build', [cipd_dir.join('ninja'), 'stage2-distribution'])
      # TODO: we should be running stage2-check-all
      api.step('check-llvm', [cipd_dir.join('ninja'), 'stage2-check-llvm'])
      api.step('check-clang', [cipd_dir.join('ninja'), 'stage2-check-clang'])
      with api.context(env={'DESTDIR': pkg_dir}):
        api.step('install',
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
      'libclang_rt.asan.so',
      'libclang_rt.ubsan_standalone.so',
      'libclang_rt.scudo.so',
  ]:
    manifest_format += ('lib/%s=clang/{clang_version}/{arch}-fuchsia/lib/%s\n' %
                        (soname, soname))
  for prefix in ('', 'asan/'):
    for soname in [
        'libc++.so.2',
        'libc++abi.so.1',
        'libunwind.so.1',
    ]:
      manifest_format += ('lib/%s=clang/{clang_version}/{arch}-fuchsia/lib/%s\n' %
                          (prefix + soname, prefix + soname))
  for _, arch in TARGET_TO_ARCH.iteritems():
    manifest_file = '%s-fuchsia.manifest' % arch
    api.file.write_text('write %s' % manifest_file,
                        pkg_dir.join('lib', manifest_file),
                        manifest_format.format(arch=arch, clang_version=clang_version))

  cipd_pkg_name = 'fuchsia/clang/' + target_platform
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

  cipd_pins = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if cipd_pins:
    api.step('Package is up-to-date', cmd=None)
    return

  cipd_pin = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': clang_version,
        'git_repository': repository,
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('clang', target_platform, cipd_pin.instance_id),
      unauthenticated_url=True
  )


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  version = 'clang version 5.0.0 (trunk 302207) (llvm/trunk 302209)'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.step_data('clang version', api.raw_io.stream_output(version)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.step_data('clang version', api.raw_io.stream_output(version)) +
           api.step_data('cipd search fuchsia/clang/' + platform + '-amd64 ' +
                         'git_revision:' + revision,
                         api.cipd.example_search('fuchsia/clang/' + platform + '-amd64 ', [])))
