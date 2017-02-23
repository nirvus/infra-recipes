# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Magenta."""

import re

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/shutil',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

TARGETS = ['magenta-qemu-arm64', 'magenta-pc-x86-64']

TEST_MATCH = re.compile(r'SUMMARY: Ran (\d+) tests: (?P<failed>\d+) failed')

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


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             toolchain):
  api.jiri.ensure_jiri()

  api.jiri.init()
  api.jiri.import_manifest(manifest, remote)
  api.jiri.update()
  step_result = api.jiri.snapshot(api.raw_io.output())
  snapshot = step_result.raw_io.output
  step_result.presentation.logs['jiri.snapshot'] = snapshot.splitlines()

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url)

  tmp_dir = api.path['tmp_base'].join('magenta_tmp')
  api.shutil.makedirs('tmp', tmp_dir)
  path = tmp_dir.join('autorun')
  api.shutil.write('write autorun', path, '''#!/bin/sh
runtests
dm poweroff''')

  build_args = [
    'make',
    '-j%s' % api.platform.cpu_count,
    target
  ]
  if toolchain == 'clang':
    build_args.append('USE_CLANG=true')
  with api.step.context({'cwd': api.path['start_dir'].join('magenta')}):
    api.step('build', build_args, env={'USER_AUTORUN': path})

  with api.step.nest('ensure_qemu'):
    with api.step.context({'infra_step': True}):
      qemu_package = ('fuchsia/tools/qemu/%s' %
          api.cipd.platform_suffix())
      qemu_dir = api.path['start_dir'].join('cipd', 'qemu')
      api.cipd.ensure(qemu_dir, {qemu_package: 'latest'})

  arch = {
      'magenta-qemu-arm64': 'arm64',
      'magenta-pc-x86-64': 'x86-64',
  }[target]

  test_args = [
    api.path['start_dir'].join('magenta', 'scripts', 'run-magenta'),
    '-a', arch,
    '-q', qemu_dir.join('bin/'),
    '-c', '-serial stdio',
  ]
  if toolchain == 'clang':
    test_args.append('-C')
  try:
    step_result = api.step(
        'test',
        test_args,
        timeout=120,
        stdin=api.raw_io.input(''),
        stdout=api.raw_io.output(),
        stderr=api.raw_io.output(),
        step_test_data=lambda:
            api.raw_io.test_api.stream_output('SUMMARY: Ran 2 tests: 1 failed')
    )
  except api.step.StepTimeout: # pragma: no cover
    step_result.presentation.status = api.step.EXCEPTION
  else:
    output = step_result.stdout
    m = TEST_MATCH.search(output)
    if not m or int(m.group('failed')) > 0:
      step_result.presentation.status = api.step.FAILURE
    step_result.presentation.logs['qemu.stdout'] = output.splitlines()


def GenTests(api):
  yield api.test('ci') + api.properties(
      manifest='magenta',
      remote='https://fuchsia.googlesource.com/manifest',
      target='magenta-pc-x86-64',
      toolchain='clang',
  )
  yield api.test('cq_try') + api.properties.tryserver(
      gerrit_project='magenta',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='magenta',
      remote='https://fuchsia.googlesource.com/manifest',
      target='magenta-pc-x86-64',
      toolchain='clang',
  )
