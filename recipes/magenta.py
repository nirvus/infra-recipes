# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Magenta."""

import re

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property, StepFailure


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'infra/qemu',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/shutil',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

TARGETS = ['magenta-qemu-arm64', 'magenta-pc-x86-64']

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
  'toolchain': Property(kind=Enum('gcc', 'clang'), help='Toolchain to use'),
}

RETURN_SCHEMA = ReturnSchema(
  got_revision=Single(str)
)


def RunTests(api, name, *args, **kwargs):
  step_result = None
  try:
    step_result = api.qemu.run(name, *args, **kwargs)
  except StepFailure as error:
    step_result = error.result
    raise
  finally:
    if step_result is not None:
      lines = step_result.stdout.splitlines()
      step_result.presentation.logs['qemu.stdout'] = lines

  m = re.search(kwargs['shutdown_pattern'], step_result.stdout)
  if not m:
    step_result.presentation.status = api.step.WARNING
    raise api.step.StepWarning('Test output missing')
  elif int(m.group('failed')) > 0:
    step_result.presentation.status = api.step.FAILURE
    raise api.step.StepFailure(m.group(0))


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             toolchain):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote)
    api.jiri.clean()
    update_result = api.jiri.update()
    revision = api.jiri.project('magenta').json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url, rebase=True)

  tmp_dir = api.path['tmp_base'].join('magenta_tmp')
  api.shutil.makedirs('tmp', tmp_dir)
  path = tmp_dir.join('autorun')
  autorun = [
    'msleep 500',
    'runtests',
    'dm poweroff',
  ]
  step_result = api.shutil.write('write autorun', path, '\n'.join(autorun))
  step_result.presentation.logs['autorun.sh'] = autorun

  build_args = [
    'make',
    '-j%s' % api.platform.cpu_count,
    target
  ]
  if toolchain == 'clang':
    build_args.append('USE_CLANG=true')

  with api.context(cwd=api.path['start_dir'].join('magenta'),
                   env={'USER_AUTORUN': path}):
    api.step('build', build_args)

  api.qemu.ensure_qemu()

  arch = {
    'magenta-qemu-arm64': 'aarch64',
    'magenta-pc-x86-64': 'x86_64',
  }[target]

  build_dir = 'build-%s' % target + ('-clang' if toolchain == 'clang' else '')
  bootdata_path = api.path['start_dir'].join(
      'magenta', build_dir, 'bootdata.bin')

  image_name = {
    'aarch64': 'magenta.elf',
    'x86_64': 'magenta.bin',
  }[arch]
  image_path = api.path['start_dir'].join('magenta', build_dir, image_name)

  # Boot and run tests.
  RunTests(api, 'run booted tests', arch, image_path, kvm=True,
      initrd=bootdata_path, shutdown_pattern=BOOTED_TESTS_MATCH,
      step_test_data=lambda:
          api.raw_io.test_api.stream_output('SUMMARY: Ran 2 tests: 1 failed'))

  return RETURN_SCHEMA.new(got_revision=revision)


def GenTests(api):
  yield (api.test('ci') +
     api.properties(manifest='magenta',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='magenta-pc-x86-64',
                    toolchain='gcc') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('cq_try') +
     api.properties.tryserver(
         gerrit_project='magenta',
         patch_gerrit_url='fuchsia-review.googlesource.com',
         manifest='magenta',
         remote='https://fuchsia.googlesource.com/manifest',
         target='magenta-pc-x86-64',
         toolchain='clang'))
  yield (api.test('failed_qemu') +
      api.properties(manifest='magenta',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='magenta-pc-x86-64',
                    toolchain='gcc') +
      api.step_data('run booted tests', retcode=1))
  yield (api.test('test_ouput') +
     api.properties(manifest='magenta',
                    remote='https://fuchsia.googlesource.com/manifest',
                    target='magenta-pc-x86-64',
                    toolchain='gcc') +
     api.step_data('run booted tests', api.raw_io.stream_output('')))
