# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building LLVM."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re

DEPS = [
    'infra/git',
    'infra/gitiles',
    'infra/goma',
    'infra/gsutil',
    'infra/hash',
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

ARCH_TO_TARGET = {
    'x86_64': 'x64',
    'aarch64': 'arm64',
}

PLATFORM_TO_TRIPLE = {
    'linux-amd64': ['x86_64-linux-gnu'],
    'linux-arm64': ['aarch64-linux-gnu'],
    'mac-amd64': ['x86_64-apple-darwin'],
    'fuchsia': ['x86_64-fuchsia', 'aarch64-fuchsia'],
}
PLATFORMS = PLATFORM_TO_TRIPLE.keys()

LLVM_PROJECT_GIT = 'https://fuchsia.googlesource.com/third_party/llvm-project'

PROPERTIES = {
    'repository':
        Property(kind=str, help='Git repository URL', default=LLVM_PROJECT_GIT),
    'branch':
        Property(kind=str, help='Git branch', default='refs/heads/master'),
    'revision':
        Property(kind=str, help='Revision', default=None),
    'platform':
        Property(kind=str, help='CIPD platform for the target', default=None),
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
  platform = platform or host_platform

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      # TODO: deduplicate this and the clang toolchain recipe
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('infra/cmake/${platform}', 'version:3.9.2')
      pkgs.add_package('infra/ninja/${platform}', 'version:1.8.2')
      pkgs.add_package('fuchsia/clang/${platform}', 'goma')
      if platform.startswith('linux'):
        pkgs.add_package('fuchsia/sysroot/%s' % platform, 'latest', 'sysroot')
      if platform.startswith('fuchsia'):
        pkgs.add_package('fuchsia/sdk/${platform}', 'latest', 'sdk')
      api.cipd.ensure(cipd_dir, pkgs)

  staging_dir = api.path.mkdtemp('llvm')
  pkg_dir = staging_dir.join('root')
  api.file.ensure_directory('create pkg root dir', pkg_dir)

  with api.context(infra_steps=True):
    llvm_dir = api.path['start_dir'].join('llvm-project')
    api.git.checkout(repository, llvm_dir, ref=revision, submodules=True)

  # build llvm
  with api.goma.build_with_goma():
    targets = PLATFORM_TO_TRIPLE[platform]
    for triple in targets:
      build_dir = staging_dir.join(
          'llvm_%s_build_dir' % triple.replace('-', '_'))
      api.file.ensure_directory('create %s llvm build dir' % triple, build_dir)

      if len(targets) > 1:
        install_dir = staging_dir.join(
            'llvm_%s_install_dir' % triple.replace('-', '_'))
        api.file.ensure_directory('create %s llvm install dir' % triple,
                                  install_dir)
      else:
        install_dir = pkg_dir

      target = ARCH_TO_TARGET[triple.split('-')[0]]
      if platform == 'fuchsia':
        sysroot = cipd_dir.join('sdk', 'arch', target, 'sysroot')
      elif platform.startswith('linux'):
        sysroot = cipd_dir.join('sysroot')
      elif platform.startswith('mac'):
        # TODO(IN-148): Eventually use our own hermetic sysroot.
        step_result = api.step(
            'xcrun', ['xcrun', '--show-sdk-path'],
            stdout=api.raw_io.output(name='sdk-path', add_output_log=True),
            step_test_data=
            lambda: api.raw_io.test_api.stream_output('/some/xcode/path'))
        sysroot = step_result.stdout.strip()

      if not platform.startswith('mac'):
        extra_options = [
            '-DCMAKE_AR=%s' % cipd_dir.join('bin', 'llvm-ar'),
            '-DCMAKE_LINKER=%s' % cipd_dir.join('bin', 'ld.lld'),
            '-DCMAKE_NM=%s' % cipd_dir.join('bin', 'llvm-nm'),
            '-DCMAKE_OBJCOPY=%s' % cipd_dir.join('bin', 'llvm-objcopy'),
            '-DCMAKE_OBJDUMP=%s' % cipd_dir.join('bin', 'llvm-objdump'),
            '-DCMAKE_RANLIB=%s' % cipd_dir.join('bin', 'llvm-ranlib'),
            '-DCMAKE_STRIP=%s' % cipd_dir.join('bin', 'llvm-strip'),
            '-DLLVM_ENABLE_LLD=ON',
        ]
      else:
        extra_options = []

      if platform != host_platform:
        system = platform.split('-')[0].replace('mac', 'darwin').capitalize()
        extra_options.append('-DCMAKE_SYSTEM_NAME=%s' % system)

      with api.context(cwd=build_dir):
        api.step('configure %s llvm' % triple, [
            cipd_dir.join('bin', 'cmake'),
            '-GNinja',
            '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
            '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
            '-DCMAKE_INSTALL_PREFIX=',
            '-DCMAKE_C_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
            '-DCMAKE_CXX_COMPILER_LAUNCHER=%s' %
            api.goma.goma_dir.join('gomacc'),
            '-DCMAKE_ASM_COMPILER_LAUNCHER=%s' %
            api.goma.goma_dir.join('gomacc'),
            '-DCMAKE_C_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
            '-DCMAKE_C_COMPILER_TARGET=%s' % triple,
            '-DCMAKE_CXX_COMPILER=%s' % cipd_dir.join('bin', 'clang++'),
            '-DCMAKE_CXX_COMPILER_TARGET=%s' % triple,
            '-DCMAKE_ASM_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
            '-DCMAKE_ASM_COMPILER_TARGET=%s' % triple,
            '-DCMAKE_SYSROOT=%s' % sysroot,
            '-DLLVM_HOST_TRIPLE=%s' % triple,
            '-DLLVM_TARGETS_TO_BUILD=X86;AArch64',
            '-DLLVM_DISTRIBUTION_COMPONENTS=llvm-headers;llvm-libraries;LLVM',
            '-DLLVM_BUILD_LLVM_DYLIB=ON',
            '-DLLVM_EXTERNALIZE_DEBUGINFO=ON',
            '-DLLVM_ENABLE_LIBXML2=OFF',
            '-DLLVM_ENABLE_TERMINFO=OFF',
            '-DLLVM_ENABLE_ZLIB=OFF',
        ] + extra_options + [llvm_dir.join('llvm')])
        api.step(
            'build %s llvm' % triple,
            [cipd_dir.join('ninja'), 'distribution',
             '-j%s' % api.goma.jobs])

        with api.context(env={'DESTDIR': install_dir}):
          api.step('install %s llvm' % triple,
                   [cipd_dir.join('ninja'), 'install-distribution'])

      if platform == 'fuchsia':
        api.file.copytree('copy %s libs' % triple,
                          install_dir.join('lib'),
                          pkg_dir.join('arch', target, 'lib'))

    if platform == 'fuchsia':
      api.python(
          'merge headers',
          api.resource('merge_headers.py'),
          args=[
              '--out',
              pkg_dir.join('pkg', 'llvm', 'include'),
              '--def1',
              '__aarch64__',
              '--def2',
              '__x86_64__',
              staging_dir.join('llvm_x86_64_fuchsia_install_dir', 'include'),
              staging_dir.join('llvm_aarch64_fuchsia_install_dir', 'include'),
          ])

  if platform == 'fuchsia':
    include_dir = pkg_dir.join('pkg', 'llvm', 'include')
  else:
    include_dir = pkg_dir.join('include')
  step_result = api.file.read_text(
      'llvm-config.h',
      include_dir.join('llvm', 'Config', 'llvm-config.h'),
      test_data='#define LLVM_VERSION_STRING "7.0.0svn"')
  m = re.search(r'LLVM_VERSION_STRING "([a-zA-Z0-9.-]+)"', step_result)
  assert m, 'Cannot determine LLVM version'
  llvm_version = m.group(1)

  cipd_pkg_name = 'fuchsia/lib/llvm/%s' % platform
  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name, package_root=pkg_dir, install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/llvm.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('llvm.cipd')

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
          'version': llvm_version,
          'git_repository': repository,
          'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('lib', 'llvm', platform, cipd_pin.instance_id),
      unauthenticated_url=True)


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  for platform in PLATFORMS:
    yield (api.test(platform.replace('-', '_') + '_existing_pkg') +
           api.properties(platform=platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)))
    yield (api.test(platform.replace('-', '_') + '_new_revision') +
           api.properties(platform=platform) + api.gitiles.refs(
               'refs', ('refs/heads/master', revision)) + api.step_data(
                   'cipd search fuchsia/lib/llvm/%s ' % platform +
                   'git_revision:' + revision, api.json.output({
                       'result': []
                   })))
