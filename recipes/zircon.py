# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Zircon."""

import re

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property, StepFailure


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'infra/qemu',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/source_manifest',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

TARGETS = [
  'zircon-qemu-arm64',
  'zircon-pc-x86-64',
  'zircon-rpi3-arm64',
  'zircon-hikey960-arm64',
  'pc-x86-64-test',
  'qemu-virt-a53-test'
]

# toolchain: (['make', 'args'], 'builddir-suffix')
TOOLCHAINS = {
  'gcc': ([], ''),
  'clang': (['USE_CLANG=true'], '-clang'),
  'asan': (['USE_ASAN=true'], '-asan'),
  'lto': (['USE_LTO=true', 'USE_THINLTO=false'], '-lto'),
  'thinlto': (['USE_LTO=true', 'USE_THINLTO=true'], '-thinlto'),
}

# Test summary from the core tests, which run directly from userboot.
CORE_TESTS_MATCH = r'CASES: +(\d+) +SUCCESS: +(\d+) +FAILED: +(?P<failed>\d+)'

# Test summary from the runtests command on a booted system.
BOOTED_TESTS_MATCH = r'SUMMARY: Ran (\d+) tests: (?P<failed>\d+) failed'

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'toolchain': Property(kind=Enum(*(TOOLCHAINS.keys())),
                        help='Toolchain to use'),
  'run_tests' : Property(kind=bool, help='Run tests in qemu after building', default=True)
}


def RunTests(api, name, build_dir, *args, **kwargs):
  step_result = None
  failure_reason = None
  try:
    step_result = api.qemu.run(name, *args, **kwargs)
  except StepFailure as error:
    step_result = error.result
    if error.retcode == 2:
      failure_reason = 'Test timed out'
    else:
      raise api.step.InfraFailure('QEMU failure')

  qemu_log = step_result.stdout
  step_result.presentation.logs['qemu.stdout'] = qemu_log.splitlines()

  if failure_reason is None:
    m = re.search(kwargs['shutdown_pattern'], qemu_log)
    if not m:
      raise api.step.InfraFailure('Test output missing')
    elif int(m.group('failed')) > 0:
      step_result.presentation.status = api.step.FAILURE
      failure_reason = m.group(0)

  if failure_reason is not None:
    symbolize_cmd = [
      api.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
      '--no-echo',
      '--build-dir', build_dir,
    ]
    symbolize_result = api.step('symbolize', symbolize_cmd,
        stdin=api.raw_io.input(data=qemu_log),
        stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized backtrace'] = symbolized_lines
      symbolize_result.presentation.status = api.step.FAILURE

    raise api.step.StepFailure(failure_reason)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             toolchain, run_tests):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, patch_ref, patch_gerrit_url)
    revision = api.jiri.project(['zircon']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  tmp_dir = api.path['tmp_base'].join('zircon_tmp')
  api.file.ensure_directory('makedirs tmp', tmp_dir)
  path = tmp_dir.join('autorun')
  autorun = ['msleep 500', 'runtests']
  api.file.write_text('write autorun', path, '\n'.join(autorun))
  api.step.active_result.presentation.logs['autorun.sh'] = autorun

  tc_args, tc_suffix = TOOLCHAINS[toolchain]
  build_args = [
    'make',
    '-j%s' % api.platform.cpu_count,
    target
  ] + tc_args

  if toolchain == 'thinlto':
    build_args.append('THINLTO_CACHE_DIR=' +
                      str(api.path['cache'].join('thinlto')))

  with api.context(cwd=api.path['start_dir'].join('zircon'),
                   env={'USER_AUTORUN': path}):
    api.step('build', build_args)

  if run_tests:
    api.qemu.ensure_qemu()

  arch = {
    'zircon-hikey960-arm64': 'aarch64',
    'zircon-rpi3-arm64': 'aarch64',
    'zircon-qemu-arm64': 'aarch64',
    'zircon-pc-x86-64': 'x86_64',
    'pc-x86-64-test': 'x86_64',
    'qemu-virt-a53-test': 'aarch64',
  }[target]

  build_dir = api.path['start_dir'].join('zircon', 'build-%s' % target + tc_suffix)
  bootdata_path = build_dir.join('bootdata.bin')

  image_path = build_dir.join({
    'aarch64': 'zircon.elf',
    'x86_64': 'zircon.bin',
  }[arch])

  if run_tests:
    # Run core tests with userboot.
    RunTests(api, 'run core tests', build_dir, arch, image_path, kvm=True,
        initrd=bootdata_path, cmdline='userboot=bin/core-tests',
        shutdown_pattern=CORE_TESTS_MATCH, timeout=300, step_test_data=lambda:
            api.raw_io.test_api.stream_output('CASES: 1 SUCCESS: 1 FAILED: 0'))

    # Boot and run tests.
    RunTests(api, 'run booted tests', build_dir, arch, image_path, kvm=True,
        initrd=bootdata_path, shutdown_pattern=BOOTED_TESTS_MATCH, timeout=1200,
        step_test_data=lambda:
            api.raw_io.test_api.stream_output('SUMMARY: Ran 2 tests: 1 failed'))


def GenTests(api):
  yield (api.test('ci') +
     api.properties(manifest='zircon',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='zircon-pc-x86-64',
                    toolchain='gcc') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('asan') +
     api.properties(manifest='zircon',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='zircon-pc-x86-64',
                    toolchain='asan') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('lto') +
     api.properties(manifest='zircon',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='zircon-pc-x86-64',
                    toolchain='lto') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('thinlto') +
     api.properties(manifest='zircon',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='zircon-pc-x86-64',
                    toolchain='thinlto') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('cq_try') +
     api.properties.tryserver(
         gerrit_project='zircon',
         patch_gerrit_url='fuchsia-review.googlesource.com',
         manifest='zircon',
         remote='https://fuchsia.googlesource.com/manifest',
         target='zircon-pc-x86-64',
         toolchain='clang'))
  yield (api.test('no_run_tests') +
     api.properties.tryserver(
         manifest='zircon',
         remote='https://fuchsia.googlesource.com/manifest',
         target='zircon-pc-x86-64',
         toolchain='clang',
         run_tests=False))
  yield (api.test('build_rpi') +
     api.properties.tryserver(
         manifest='zircon',
         remote='https://fuchsia.googlesource.com/manifest',
         target='zircon-rpi3-arm64',
         toolchain='clang',
         run_tests=False))
  yield (api.test('failed_qemu') +
      api.properties(manifest='zircon',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='zircon-pc-x86-64',
                    toolchain='gcc') +
      api.step_data('run booted tests', retcode=1))
  yield (api.test('qemu_timeout') +
      api.properties(manifest='zircon',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='zircon-pc-x86-64',
                    toolchain='gcc') +
      api.step_data('run booted tests', retcode=2))
  yield (api.test('test_ouput') +
      api.properties(manifest='zircon',
                     remote='https://fuchsia.googlesource.com/manifest',
                     target='zircon-pc-x86-64',
                     toolchain='gcc') +
      api.step_data('run booted tests', api.raw_io.stream_output('')))
  yield (api.test('symbolized_output') +
      api.properties(manifest='zircon',
                     remote='https://fuchsia.googlesource.com/manifest',
                     target='zircon-pc-x86-64',
                     toolchain='gcc') +
      api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n')))
