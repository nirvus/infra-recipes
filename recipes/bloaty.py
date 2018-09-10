# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building Bloaty."""

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'infra/git',
    'infra/gitiles',
    'infra/go',
    'infra/goma',
    'infra/gsutil',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
]

PROPERTIES = {
    'repository':
        Property(
            kind=str,
            help='Git repository URL',
            default='https://fuchsia.googlesource.com/third_party/bloaty'),
    'branch':
        Property(kind=str, help='Git branch', default='refs/heads/master'),
    'revision':
        Property(kind=str, help='Revision', default=None),
    'platform':
        Property(kind=str, help='CIPD target platform', default=None),
}

PLATFORM_TO_TRIPLE = {
    'linux-amd64': 'x86_64-linux-gnu',
    'linux-arm64': 'aarch64-linux-gnu',
    'mac-amd64': 'x86_64-apple-darwin',
}
PLATFORMS = PLATFORM_TO_TRIPLE.keys()


def platform_sysroot(api, cipd_dir, platform):
  if platform.startswith('linux'):
    return cipd_dir.join('sysroot')
  elif platform.startswith('mac'):  # pragma: no cover
    # TODO(IN-148): Eventually use our own hermetic sysroot as for Linux.
    step_result = api.step(
        'xcrun', ['xcrun', '--show-sdk-path'],
        stdout=api.raw_io.output(name='sdk-path', add_output_log=True),
        step_test_data=
        lambda: api.raw_io.test_api.stream_output('/some/xcode/path'))
    return step_result.stdout.strip()


def cmake(api, cipd_dir, src_dir, platform, options=[], step_name='cmake'):
  sysroot = platform_sysroot(api, cipd_dir, platform)
  if platform.startswith('linux'):
    options.extend([
        '-DCMAKE_LINKER=%s' % cipd_dir.join('bin', 'ld.lld'),
        '-DCMAKE_NM=%s' % cipd_dir.join('bin', 'llvm-nm'),
        '-DCMAKE_OBJCOPY=%s' % cipd_dir.join('bin', 'llvm-objcopy'),
        '-DCMAKE_OBJDUMP=%s' % cipd_dir.join('bin', 'llvm-objdump'),
        '-DCMAKE_RANLIB=%s' % cipd_dir.join('bin', 'llvm-ranlib'),
        '-DCMAKE_STRIP=%s' % cipd_dir.join('bin', 'llvm-strip'),
        '-DCMAKE_EXE_LINKER_FLAGS=-static-libstdc++ -ldl -lpthread',
    ])

  target = PLATFORM_TO_TRIPLE[platform]
  return api.step(step_name, [
      cipd_dir.join('bin', 'cmake'),
      '-GNinja',
      '-DCMAKE_BUILD_TYPE=Release',
      '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
      '-DCMAKE_C_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
      '-DCMAKE_C_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
      '-DCMAKE_C_COMPILER_TARGET=%s' % target,
      '-DCMAKE_CXX_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
      '-DCMAKE_CXX_COMPILER=%s' % cipd_dir.join('bin', 'clang++'),
      '-DCMAKE_CXX_COMPILER_TARGET=%s' % target,
  ] + options + [src_dir])


def upload_package(api, pkg_name, pkg_file, pkg_dir, repository, revision):
  pkg_def = api.cipd.PackageDefinition(
      package_name=pkg_name, package_root=pkg_dir, install_mode='copy')
  pkg_def.add_file(pkg_file)
  pkg_def.add_version_file('.versions/%s.cipd_version' % pkg_name)

  cipd_pkg_file = api.path['cleanup'].join(pkg_name)
  api.file.ensure_directory('ensure cipd dir', api.path.dirname(cipd_pkg_file))
  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )

  cipd_pins = api.cipd.search(pkg_name, 'git_revision:' + revision)
  if cipd_pins:
    api.step('Package is up-to-date', cmd=None)
    return

  cipd_pin = api.cipd.register(
      package_name=pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'git_repository': repository,
          'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join(pkg_name, cipd_pin.instance_id),
      unauthenticated_url=True)


def RunSteps(api, repository, branch, revision, platform):
  api.goma.ensure_goma()
  api.gsutil.ensure_gsutil()

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

  src_dir = api.path['start_dir'].join('bloaty_src')
  with api.context(infra_steps=True):
    revision = api.git.checkout(
        repository, src_dir, ref=revision, submodules=True)

  build_dir = api.path['start_dir'].join('bloaty_build')
  api.file.ensure_directory('ensure build dir', build_dir)

  cipd_dir = api.path['start_dir'].join('cipd')
  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('infra/cmake/${platform}', 'version:3.9.2')
      pkgs.add_package('infra/ninja/${platform}', 'version:1.8.2')
      pkgs.add_package('fuchsia/clang/${platform}', 'goma')
      if target_platform.startswith('linux'):
        pkgs.add_package('fuchsia/sysroot/%s' % target_platform, 'latest',
                         'sysroot')
      api.cipd.ensure(cipd_dir, pkgs)

  target = PLATFORM_TO_TRIPLE[target_platform]

  with api.goma.build_with_goma():
    with api.context(cwd=build_dir):
      cmake(api, cipd_dir, src_dir, target_platform)
      api.step('build', [cipd_dir.join('ninja'), '-j%d' % api.goma.jobs])
      api.step('test', [cipd_dir.join('ninja'), 'test'])

  upload_package(api, "fuchsia/third_party/bloaty/" + target_platform,
                 build_dir.join('bloaty'), build_dir, repository, revision)


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  for platform in ['linux', 'mac']:
    yield (api.test(platform) + api.platform.name(platform) +
           api.properties(platform=platform + '-amd64'))
    yield (api.test(platform + '_new') + api.platform.name(platform) +
           api.properties(platform=platform + '-amd64') + api.step_data(
               'cipd search fuchsia/third_party/bloaty/' + platform + '-amd64 '
               + 'git_revision:deadbeef',
               api.cipd.example_search(
                   'fuchsia/third_party/bloaty/' + platform + '-amd64 ', [])))
  yield (api.test('linux_arm64') + api.platform.name('linux') +
         api.properties(platform='linux-arm64'))
