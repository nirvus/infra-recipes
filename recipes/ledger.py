# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Ledger and running tests."""

import re

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/jiri',
  'infra/qemu',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/shutil',
  'recipe_engine/step',
]

TEST_BINARIES = [
  '/system/test/ledger_unittests',
  '/system/test/ledger_integration_tests',
]

TESTS_TOTAL_PATTERN = r'(\d+) tests from \d+ test cases ran\.'
TESTS_PASSED_PATTERN = r'\[  PASSED  \] (\d+) tests\.'

FAKE_TEST_OUTPUT = """
  3 tests from 1 test cases ran.
  [  PASSED  ] 3 tests.
  3 tests from 1 test cases ran.
  [  PASSED  ] 2 tests.
"""

TARGETS = ['arm64', 'x86-64']

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
  'build_type': Property(kind=Enum('debug', 'release'), help='The build type',
                         default='debug'),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             build_type):
  api.goma.ensure_goma()
  api.jiri.ensure_jiri()
  api.qemu.ensure_qemu()

  api.jiri.init()
  api.jiri.import_manifest(manifest, remote)
  api.jiri.clean_project()
  api.jiri.update()
  step_result = api.jiri.snapshot(api.raw_io.output())
  snapshot = step_result.raw_io.output
  step_result.presentation.logs['jiri.snapshot'] = snapshot.splitlines()

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url)

  release_build = (build_type == 'release')
  out_dir_prefix = 'out/release-%s' if release_build else 'out/debug-%s'

  # Step: create autorun script
  tmp_dir = api.path['tmp_base'].join('magenta_tmp')
  api.shutil.makedirs('makedirs', tmp_dir)
  autorun_path = tmp_dir.join('autorun')
  autorun_script = '\n'.join(TEST_BINARIES + ['msleep 250', 'dm poweroff'])
  api.shutil.write('write %s' % autorun_path, autorun_path, autorun_script)

  # Step: build magenta
  magenta_target = {
    'arm64': 'magenta-qemu-arm64',
    'x86-64': 'magenta-pc-x86-64',
  }[target]
  build_args = [
    'make',
    '-j%s' % api.platform.cpu_count,
    magenta_target,
  ]
  with api.step.context({'cwd': api.path['start_dir'].join('magenta')}):
    api.step('build magenta', build_args)

  # Step: build sysroot
  sysroot_target = {'arm64': 'aarch64', 'x86-64': 'x86_64'}[target]
  build_sysroot_cmd_params = \
      ['scripts/build-sysroot.sh', '-c', '-t', sysroot_target]
  if release_build:
    build_sysroot_cmd_params.append('-r')

  api.step(
      'build sysroot',
      build_sysroot_cmd_params)

  fuchsia_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]

  # Step: build Fuchsia
  with api.step.nest('build Fuchsia'), api.goma.build_with_goma():
    gen_cmd_params = [
      'packages/gn/gen.py',
      '--target_cpu=%s' % fuchsia_target,
      '--autorun=%s' % autorun_path,
      '--goma=%s' % api.goma.goma_dir,
    ]

    if release_build:
      gen_cmd_params.append('--release')

    # Include boringssl because the Ledger tests use it.
    # Include runtime because it triggers /system/autorun on startup.
    gen_cmd_params.append('--modules=ledger,boringssl,runtime')

    api.step('gen', gen_cmd_params)
    api.step(
        'ninja',
        ['buildtools/ninja', '-C', out_dir_prefix % fuchsia_target,
         '-j', api.goma.recommended_goma_jobs])

  # Step: run tests in qemu
  magenta_image_name = {
    'arm64': 'magenta.elf',
    'x86-64': 'magenta.bin',
  }[target]
  magenta_image_path = api.path['start_dir'].join(
    'magenta', 'build-%s' % magenta_target, magenta_image_name)
  bootfs_path = api.path['start_dir'].join(
    'out', '%s-%s' % (build_type, fuchsia_target), 'user.bootfs')

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]
  step_result = api.qemu.run(
      'test',
      qemu_arch,
      magenta_image_path,
      kvm=True,
      initrd=bootfs_path,
      step_test_data=(lambda:
          api.raw_io.test_api.stream_output(FAKE_TEST_OUTPUT)))

  output = step_result.stdout
  step_result.presentation.logs['qemu.stdout'] = output.splitlines()

  tests_total_match = re.findall(TESTS_TOTAL_PATTERN, output)
  tests_passed_match = re.findall(TESTS_PASSED_PATTERN, output)
  tests_total = sum(int(num) for num in tests_total_match)
  tests_failed = tests_total - sum(int(num) for num in tests_passed_match)

  exception = None
  if len(tests_total_match) != len(TEST_BINARIES):
    exception = api.step.StepFailure('Unable to parse test output')
  if tests_failed:
    exception = api.step.StepFailure('%d out of %d tests failed' % (
        tests_failed, tests_total))

  if exception:
    step_result.presentation.status = api.step.FAILURE
    raise exception

def GenTests(api):
  yield api.test('ci') + api.properties(
      manifest='userspace',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  )
  yield api.test('cq_try') + api.properties.tryserver(
      gerrit_project='ledger',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='userspace',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  )
  yield api.test('invalid_test_output') + api.properties(
      manifest='userspace',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64') + api.step_data('test', api.raw_io.stream_output(''))
