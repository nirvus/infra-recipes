# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Builds the Fuchsia Dart test image and runs the Dart tests."""

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/gsutil',
  'infra/jiri',
  'infra/qemu',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/source_manifest',
  'recipe_engine/step',
]

TARGETS = ['arm64', 'x86-64']

TESTS_PASSED = 'all tests passed'
TESTS_FAILED = 'tests failed'
TEST_SHUTDOWN = 'ready for fuchsia shutdown'

# The kernel binary to pass to qemu.
ZIRCON_IMAGE_NAME = 'zircon.bin'

# The boot filesystem image.
BOOTFS_IMAGE_NAME = 'user.bootfs'

# The /system-relative path of the autorun script created by
# RUNCMDS_PACKAGE.
RUNCMDS_BOOTFS_PATH = 'data/infra/runcmds'

RUNCMDS_PACKAGE = '''
{
    "resources": [
        {
            "bootfs_path": "%(bootfs_path)s",
            "file": "%(file)s"
        }
    ]
}
'''

PROPERTIES = {
  'manifest': Property(kind=str, help='Jiri manifest to use',
                       default='fuchsia'),
  'remote': Property(kind=str, help='Remote manifest repository',
                     default='https://fuchsia.googlesource.com/manifest'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build',
                     default='x86-64'),
  'build_type': Property(kind=Enum('debug', 'release'),
                         help='The build type', default='debug'),
  'goma_dir': Property(kind=str, help='Path to goma', default=None),
}


def Checkout(api, manifest, remote):
  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote)
    snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
    api.jiri.snapshot(snapshot_file)


def BuildZircon(api, zircon_project):
  build_zircon_cmd = [
    api.path['start_dir'].join('scripts', 'build-zircon.sh'),
    '-c',
    '-p', zircon_project,
  ]
  api.step('build zircon', build_zircon_cmd)


def BuildFuchsia(api, build_type, target, gn_target, zircon_project,
                 fuchsia_build_dir):
  runcmds = [
    '#!/boot/bin/sh',
    'msleep 500',
    'cd /system/test/dart',
    # Print a different message depending on whether the test command passes
    # or fails. This is necessary because Dart tests are silent when they pass.
    'dart --checked tools/testing/dart/main.dart --progress=line -m %s -a x64 -r vm vm && echo %s || echo %s' % (
        build_type, TESTS_PASSED, TESTS_FAILED),
    'echo "%s"' % TEST_SHUTDOWN,
  ]
  runcmds_path = api.path['tmp_base'].join('runcmds')
  api.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
  api.step.active_result.presentation.logs['runcmds'] = runcmds

  runcmds_package_path = api.path['tmp_base'].join('runcmds_package')
  runcmds_package = RUNCMDS_PACKAGE % {
      'file': runcmds_path, 'bootfs_path': RUNCMDS_BOOTFS_PATH
  }
  api.file.write_text('write runcmds package', runcmds_package_path, runcmds_package)
  api.step.active_result.presentation.logs['runcmds_package'] = runcmds_package.splitlines()

  packages = [
    'topaz/packages/default',
    'build/packages/bootfs', # TODO(abarth): Remove once INTK-99 is fixed.
    str(runcmds_package_path),
  ]

  goma_env = {}
  if api.properties.get('goma_local_cache', False):
    goma_env['GOMA_LOCAL_OUTPUT_CACHE_DIR'] = api.path['cache'].join('goma', 'localoutputcache')

  with api.step.nest('build fuchsia'):
    with api.goma.build_with_goma(env=goma_env):
      gen_cmd = [
        api.path['start_dir'].join('build', 'gn', 'gen.py'),
        '--target_cpu', gn_target,
        '--packages', ','.join(packages),
        '--platforms=%s' % zircon_project,
      ]

      gen_cmd.append('--goma=%s' % api.goma.goma_dir)

      if build_type == 'release':
        gen_cmd.append('--release')

      gen_cmd.append(
          '--args=extra_bootdata = [ "//third_party/dart:dart_test_bootfs" ]')

      api.step('gen', gen_cmd)

      ninja_cmd = [
        api.path['start_dir'].join('buildtools', 'ninja'),
        '-C', fuchsia_build_dir,
        '-j', api.goma.recommended_goma_jobs,
      ]

      api.step('ninja', ninja_cmd)


def RunTests(api, target, fuchsia_build_dir):
  zircon_build_dir = {
    'arm64': 'build-zircon-qemu-arm64',
    'x86-64': 'build-zircon-pc-x86-64',
  }[target]

  zircon_image_path = api.path['start_dir'].join(
    'out', 'build-zircon', zircon_build_dir, ZIRCON_IMAGE_NAME)

  bootfs_path = fuchsia_build_dir.join(BOOTFS_IMAGE_NAME)

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

  run_tests_result = None
  failure_reason = None

  try:
    run_tests_result = api.qemu.run(
        'run tests',
        qemu_arch,
        zircon_image_path,
        kvm=True,
        memory=4096,
        initrd=bootfs_path,
        cmdline='zircon.autorun.system=/system/%s' % RUNCMDS_BOOTFS_PATH,
        shutdown_pattern=TEST_SHUTDOWN)
  except api.step.StepFailure as error:
    run_tests_result = error.result
    if error.retcode == 2:
      failure_reason = 'Tests timed out'
    else:
      raise api.step.InfraFailure('QEMU failure')

  qemu_log = run_tests_result.stdout
  run_tests_result.presentation.logs['qemu log'] = qemu_log.splitlines()

  if failure_reason is None:
    if TESTS_PASSED in qemu_log:
      pass
    elif TESTS_FAILED in qemu_log:
      run_tests_result.presentation.status = api.step.FAILURE
      failure_reason = 'Tests failed'
    else:
      run_tests_result.presentation.status = api.step.EXCEPTION
      failure_reason = 'Missing test status message'

  if failure_reason is not None:
    symbolize_cmd = [
      api.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
      '--no-echo',
      '--build-dir', fuchsia_build_dir,
    ]
    symbolize_result = api.step('symbolize', symbolize_cmd,
        stdin=api.raw_io.input(data=qemu_log),
        stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized backtraces'] = symbolized_lines
      symbolize_result.presentation.status = api.step.FAILURE

    raise api.step.StepFailure(failure_reason)


def RunSteps(api, manifest, remote, target, build_type, goma_dir):
  gn_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]
  fuchsia_out_dir = api.path['start_dir'].join('out')
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_type, gn_target))

  zircon_project = {
    'arm64': 'arm64',
    'x86-64': 'x86'
  }[target]

  if goma_dir:
    api.goma.set_goma_dir(goma_dir)

  api.jiri.ensure_jiri()
  api.gsutil.ensure_gsutil()
  api.qemu.ensure_qemu()
  api.goma.ensure_goma()

  Checkout(api, manifest, remote)

  BuildZircon(api, zircon_project)
  BuildFuchsia(
      api, build_type, target, gn_target, zircon_project, fuchsia_build_dir)

  RunTests(api, target, fuchsia_build_dir)


def GenTests(api):
  yield api.test('passing_tests') + api.properties() + api.step_data(
      'run tests', api.raw_io.stream_output(TESTS_PASSED + '\n' + TEST_SHUTDOWN))
  yield api.test('failing_tests') + api.properties() + api.step_data(
      'run tests', api.raw_io.stream_output(TESTS_FAILED + '\n' + TEST_SHUTDOWN))
  yield api.test('missing_message') + api.properties()
  yield api.test('qemu_failure') + api.properties() + api.step_data(
      'run tests', retcode=1)
  yield api.test('timeout') + api.properties() + api.step_data(
      'run tests', retcode=2)
  yield api.test('autorun_backtrace') + api.properties() + api.step_data(
      'run tests', api.raw_io.stream_output(TESTS_FAILED + '\n' + TEST_SHUTDOWN)) + api.step_data(
      'symbolize', api.raw_io.stream_output('bt1\nbt2\n'))
  yield api.test('goma_dir') + api.properties(goma_dir='/goma')
  yield api.test('goma_local_cache') + api.properties(goma_local_cache=True)
  yield api.test('release') + api.properties(build_type='release')
