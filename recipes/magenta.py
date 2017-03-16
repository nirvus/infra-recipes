# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Magenta."""

import re

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'infra/qemu',
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

RETURN_SCHEMA = ReturnSchema(
  got_revision=Single(str)
)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             toolchain):
  api.jiri.ensure_jiri()

  with api.step.context({'infra_step': True}):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote)
    api.jiri.clean_project()
    update_result = api.jiri.update()
    revision = api.jiri.project('magenta').json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url, rebase=True)

  tmp_dir = api.path['tmp_base'].join('magenta_tmp')
  api.shutil.makedirs('tmp', tmp_dir)
  path = tmp_dir.join('autorun')
  api.shutil.write('write autorun', path, '''msleep 500
runtests
msleep 250
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

  api.qemu.ensure_qemu()

  arch = {
    'magenta-qemu-arm64': 'aarch64',
    'magenta-pc-x86-64': 'x86_64',
  }[target]
  build_dir = 'build-%s' % target + ('-clang' if toolchain == 'clang' else '')
  image = {
    'aarch64': 'magenta.elf',
    'x86_64': 'magenta.bin',
  }[arch]

  step_result = api.qemu.run('test', arch,
      api.path['start_dir'].join('magenta', build_dir, image), kvm=True,
      initrd=api.path['start_dir'].join('magenta', build_dir, 'bootdata.bin'),
      step_test_data=lambda:
          api.raw_io.test_api.stream_output('SUMMARY: Ran 2 tests: 1 failed')
  )
  step_result.presentation.logs['qemu.stdout'] = step_result.stdout.splitlines()
  m = TEST_MATCH.search(step_result.stdout)
  if not m:
    step_result.presentation.status = api.step.WARNING
    raise api.step.StepWarning('Test output missing')
  elif int(m.group('failed')) > 0:
    step_result.presentation.status = api.step.FAILURE
    raise api.step.StepFailure(m.group(0))

  return RETURN_SCHEMA.new(got_revision=revision)


def GenTests(api):
  yield (api.test('ci') +
         api.properties(manifest='magenta',
                        remote='https://fuchsia.googlesource.com/manifest',
                        target='magenta-pc-x86-64',
                        toolchain='gcc') +
         api.step_data('test',
             api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('cq_try') +
         api.properties.tryserver(
             gerrit_project='magenta',
             patch_gerrit_url='fuchsia-review.googlesource.com',
             manifest='magenta',
             remote='https://fuchsia.googlesource.com/manifest',
             target='magenta-pc-x86-64',
             toolchain='clang'))
  yield (api.test('test_ouput') +
         api.properties(manifest='magenta',
                        remote='https://fuchsia.googlesource.com/manifest',
                        target='magenta-pc-x86-64',
                        toolchain='gcc') +
         api.step_data('test', api.raw_io.stream_output('')))
