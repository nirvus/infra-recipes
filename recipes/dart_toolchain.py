# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Dart toolchain."""

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/goma',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

DEPOT_TOOLS_GIT = 'https://chromium.googlesource.com/chromium/tools/depot_tools'
DART_SDK_GIT = 'https://dart.googlesource.com/sdk.git'

PROPERTIES = {
  'repository':
      Property(kind=str, help='Git repository URL', default=DART_SDK_GIT),
  'branch':
      Property(kind=str, help='Git branch', default='refs/heads/master'),
  'revision':
      Property(kind=str, help='Revision', default=None),
  'host_cpu': Property(kind=Enum('arm64', 'x64'),
                       help='GN $host_cpu toolchain will run on',
                       default=None),
  'host_os': Property(kind=Enum('linux', 'mac'),
                      help='GN $host_os toolchain will run on',
                      default=None),
}

# Fuchsia targets the toolchain must support.
FUCHSIA_TARGETS = [
  'arm64',
  'x64',
]

GN_CIPD_CPU_MAP = {
  'x64': 'amd64',
}


def RunSteps(api, repository, branch, revision, host_cpu, host_os):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()

  if not host_cpu:
    # TODO(mcgrathr): Native bots are all x64 and api.platform.arch is useless.
    host_cpu = 'x64'
  if not host_os:
    host_os = api.platform.name
  cipd_platform = '%s-%s' % (host_os, GN_CIPD_CPU_MAP.get(host_cpu, host_cpu))

  if not revision:
    revision = api.gitiles.refs(repository).get(branch, None)
  cipd_pkg_name = 'fuchsia/dart-sdk/' + cipd_platform
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
      if host_os == 'linux':
        packages['fuchsia/sysroot/%s' % cipd_platform] = 'latest'
      api.cipd.ensure(cipd_dir, packages)

  ninja = [
      cipd_dir.join('ninja'),
      '-j',
      api.goma.jobs,
      '-l',
      api.platform.cpu_count,
  ]

  # TODO(mcgrathr): Move this logic into a host_build recipe module shared
  # with gcc_toolchain.py and others.
  if host_os == 'linux':
    host_sysroot = cipd_dir
  elif host_os == 'mac':
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
    with api.step.nest('depot_tools'):
      # TODO(phosek): Move this to a named cache so it's shared across builds.
      depot_tools_dir = api.path['start_dir'].join('depot_tools')
      api.git.checkout(DEPOT_TOOLS_GIT, depot_tools_dir, submodules=False)

    with api.step.nest('dart-sdk'):
      dart_sdk_dir = api.path['start_dir'].join('dart', 'sdk')
      api.git.checkout(repository, dart_sdk_dir, ref=revision, submodules=False)

  # Use gclient to fetch the DEPS, but don't let it change dart/sdk itself.
  dart_dir = api.path['start_dir'].join('dart')
  with api.context(infra_steps=True, cwd=dart_dir,
                   env_prefixes={'PATH': [depot_tools_dir]}):
    api.step('gclient config', [
        'gclient',
        'config',
        '--unmanaged',
        # TODO(mcgrathr): Set --cache-dir?
        '-v',
        DART_SDK_GIT,
    ])
    api.step('gclient sync', [
        'gclient',
        'sync',
        '--no-history',
        '-v',
        '--output-json',
        api.json.output(),
    ])

  dart_targets = sorted(set([host_cpu] +
                            ['sim' + cpu if cpu != host_cpu else cpu
                             for cpu in FUCHSIA_TARGETS]))

  gn_common = [
      'tools/gn.py',
      '-v',
      '--mode=release',
      '--goma',
      # It actually wants a sysroot for the build host regardless of what
      # Dart target CPU the build is configured for, but wants it in the
      # form `%(target_cpu)s=%(host_sysroot)s`.
      '--target-sysroot=' + ','.join('%s=%s' % (cpu, host_sysroot)
                                     for cpu in dart_targets),
  ]

  # These are the names used by tools/gn.py.
  if api.platform.name == 'mac':
    out_prefix = 'xcodebuild'
  else:
    out_prefix = 'out'
  def out_dir(cpu):
    return dart_sdk_dir.join(out_prefix, 'Release' + cpu.upper())

  with api.goma.build_with_goma(), api.context(cwd=dart_sdk_dir):
    api.step('gn host (%s)' % host_cpu,
             gn_common + ['--arch=%s' % host_cpu, '--platform-sdk'])
    for cpu in dart_targets:
      if cpu != host_cpu:
        api.step('gn %s' % cpu, gn_common + ['--arch=%s' % cpu])
    api.step('build host (%s) SDK' % host_cpu, ninja + [
        '-C',
        out_dir(host_cpu),
        'create_sdk',
        'gen_snapshot',
        'gen_snapshot_product',
    ])
    for cpu in dart_targets:
      api.step('build %s' % cpu, ninja + [
          '-C',
          out_dir(cpu),
          'gen_snapshot_fuchsia',
          'gen_snapshot_product_fuchsia',
          'runtime',
      ])
    api.step('run tests', [
        'tools/test.py',
        '--mode=release',
        '--arch=%s' % ','.join(dart_targets),
        '--progress=line',
        '--report',
        '--time',
        '--runtime=vm',
        '--compiler=dartk',
        '--strong',
        'vm',
        'language',
    ])

  with api.step.nest('install'):
    pkg_dir = api.path['cleanup'].join('dart-sdk')
    api.file.copytree('install dart-sdk',
                      out_dir(host_cpu).join('dart-sdk'),
                      pkg_dir,
                      symlinks=True)
    for cpu, is_host in [(host_cpu, True)] + [(cpu, False)
                                              for cpu in dart_targets]:
      exe_dir = out_dir(cpu).join('exe.stripped')
      if not is_host and cpu.startswith('sim'):
        cpu = cpu[3:]
      for tool in ['gen_snapshot', 'gen_snapshot_product']:
        src = exe_dir.join(tool + ('' if is_host else '_fuchsia'))
        dst_name = '%s.%s-%s' % (tool, host_os if is_host else 'fuchsia', cpu)
        dst = pkg_dir.join('bin', dst_name)
        api.file.copy('install %s' % dst_name, src, dst)

  dart_sdk_version = api.file.read_text(
      'read dart-sdk version',
      pkg_dir.join('version'),
      test_data='2.0.0-edge.' + revision + '\n',
  ).strip()

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=pkg_dir,
      install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/dart-sdk.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('dart-sdk.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'git_repository': repository,
          'git_revision': revision,
          'dart_sdk_version': dart_sdk_version,
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
  for host_os, host_cpu, cipd_host_cpu in [('linux', 'arm64', 'arm64')]:
    cipd_platform = host_os + '-' + cipd_host_cpu
    yield (api.test(host_os + '_cross') +
           api.platform.name(host_os) +
           api.properties(host_cpu=host_cpu, host_os=host_os) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.step_data(
               'cipd search fuchsia/dart-sdk/' + cipd_platform + ' ' +
               'git_revision:' + revision,
               api.json.output({'result': []})) +
           api.step_data('gclient sync', api.json.output({'solutions': {}})))
