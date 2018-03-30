# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Dart toolchain."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/goma',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

DART_SDK_GIT = 'https://dart.googlesource.com/sdk.git'

PROPERTIES = {
  'url': Property(kind=str, help='Git repository URL', default=DART_SDK_GIT),
  'ref': Property(kind=str, help='Git reference', default='refs/heads/master'),
  'revision': Property(kind=str, help='Revision', default=None),
}


def RunSteps(api, url, ref, revision):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()

  if not revision:
    revision = api.gitiles.refs(url).get(ref, None)
  cipd_pkg_name = 'fuchsia/dart-sdk/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      packages = {
        'infra/ninja/${platform}': 'version:1.8.2',
      }
      if api.platform.name == 'linux':
        packages.update({
          'fuchsia/sysroot/${platform}': 'latest'
        })
      api.cipd.ensure(cipd_dir, packages)

  # TODO(mcgrathr): Move this logic into a host_build recipe module shared
  # with gcc_toolchain.py and others.
  if api.platform.name == 'linux':
    host_sysroot = cipd_dir
  elif api.platform.name == 'mac':
    with api.context(infra_steps=True):
      step_result = api.step(
          'xcrun', ['xcrun', '--show-sdk-path'],
          stdout=api.raw_io.output(name='sdk-path', add_output_log=True),
          step_test_data=lambda: api.raw_io.test_api.stream_output(
              '/some/xcode/path'))
      host_sysroot = step_result.stdout.strip()
  else: # pragma: no cover
    assert false, "what platform?"

  with api.context(infra_steps=True):
    api.jiri.ensure_jiri()
    api.jiri.checkout(
        manifest='dart_toolchain',
        remote='https://fuchsia.googlesource.com/manifest',
        project='manifest',
    )

  # Use gclient to fetch the DEPS, but don't let it change dart/sdk itself.
  dart_dir = api.path['start_dir'].join('dart')
  with api.context(infra_steps=True, cwd=dart_dir,
                   env_prefixes={'PATH': [
                       api.path['start_dir'].join('depot_tools')]}):
    api.step('gclient config', [
        'gclient',
        'config',
        '--unmanaged',
        # TODO(mcgrathr): Set --cache-dir?
        '-v',
        DART_SDK_GIT,
    ])
    api.step('pin git', ['git', '-C', 'sdk', 'checkout', revision])
    api.step('gclient sync', [
        'gclient',
        'sync',
        '--no-history',
        '-v',
        '--output-json',
        api.json.output(),
    ])

  dart_sdk_dir = dart_dir.join('sdk')
  gn_common = [
      'tools/gn.py',
      '-v',
      '--mode=release',
      '--goma',
      '--target-sysroot=%s' % host_sysroot,
  ]
  # These are the names used by tools/gn.py.
  out_x64_dir = dart_sdk_dir.join('out', 'ReleaseX64')
  out_arm64_dir = dart_sdk_dir.join('out', 'ReleaseSIMARM64')
  ninja_common = [
      cipd_dir.join('ninja'),
      '-j%d' % api.goma.recommended_goma_jobs,
      'gen_snapshot',
      'gen_snapshot_product',
      'runtime',
  ]
  with api.goma.build_with_goma(), api.context(cwd=dart_sdk_dir):
    api.step('gn x64', gn_common + ['--arch=x64', '--platform-sdk'])
    api.step('gn arm64', gn_common + ['--arch=simarm64'])
    api.step('build x64', ninja_common + ['-C', out_x64_dir, 'create_sdk'])
    api.step('build arm64', ninja_common + ['-C', out_arm64_dir])
    api.step('run tests', [
      'tools/test.py',
      '--mode=release',
      '--arch=x64,simarm64',
      '--progress=line',
      '--report',
      '--time',
      '--runtime=vm',
      'vm',
      'language',
    ])

  with api.step.nest('install'):
    pkg_dir = api.path.mkdtemp('dart-sdk')
    api.file.copytree('install dart-sdk',
                      out_x64_dir.join('dart-sdk'),
                      pkg_dir.join('dart-sdk'),
                      symlinks=True)
    for out_dir, install_suffix in [(out_x64_dir, 'x64'),
                                    (out_arm64_dir, 'arm64')]:
      for filename in ['gen_snapshot', 'gen_snapshot_product']:
        dest_filename = '%s.%s' % (filename, install_suffix)
        api.file.copy('install %s' % dest_filename,
                      out_dir.join('exe.stripped', filename),
                      pkg_dir.join('dest_filename'))

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=pkg_dir,
      install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/dart-sdk.cipd_version')

  cipd_pkg_file = api.path['tmp_base'].join('dart-sdk.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'git_repository': DART_SDK_GIT,
        'git_revision': revision,
      },
  )


def GenTests(api):
  revision = '301b5a1f16414bc031091eb214ddd6c589e6ed9a'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.step_data(
               'cipd search fuchsia/dart-sdk/' + platform + '-amd64 ' +
               'git_revision:' + revision,
               api.json.output({'result': []})) +
           api.step_data('gclient sync', api.json.output({'solutions': {}})))
