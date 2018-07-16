# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for running CQ-blocking clang-tidy checks."""

from contextlib import contextmanager

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

DEPS = [
    'infra/cipd',
    'infra/clang_tidy',
    'infra/fuchsia',
    'infra/git',
    'infra/goma',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/tricium',
]

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

PROPERTIES = {
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use', default=None),
    'remote':
        Property(kind=str, help='Remote manifest repository', default=None),
    'revision':
        Property(
            kind=str, help='Revision which triggered this build.',
            default=None),
    # Properties for applying a change from Gerrit as a patch.
    # NOTE: in the case of checkout_snapshot, these are treated as applying
    # to the snapshot, and not the full checkout.
    'patch_gerrit_url':
        Property(kind=str, help='Gerrit host', default=None),
    'patch_project':
        Property(kind=str, help='Gerrit project', default=None),
    'patch_ref':
        Property(kind=str, help='Gerrit patch ref', default=None),
    'checks':
        Property(
            kind=List(basestring),
            help='Checks for clang-tidy to run',
            default=['*']),
}


def RunSteps(api, manifest, remote, project, revision, patch_gerrit_url,
             patch_project, patch_ref, checks):
  api.goma.ensure_goma()
  api.clang_tidy.ensure_clang()

  checkout_result = api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      revision=revision,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      patch_ref=patch_ref,
  )
  compile_commands = api.clang_tidy.gen_compile_commands(checkout_result)

  with api.step.nest('clang-tidy'):
    show_step_result = api.git(
        'show',
        '--name-only',
        '--pretty=',
        name='get changed files',
        stdout=api.raw_io.output())
    if show_step_result.stdout:
      checks_with_errors = set()
      files = show_step_result.stdout.split('\n')
      for f in files:
        errors = api.clang_tidy.run(f, f, compile_commands, checks)
        for check in errors:
          checks_with_errors.add(check)

      if len(checks_with_errors) > 0:
        raise api.step.StepFailure(
            'clang-tidy errors found for checks: %s' % ', '.join(errors.keys()))


def GenTests(api):
  show_output = '''path/to/file
other/path/to/file'''

  compile_commands_output = '[]'

  has_errors = '''- DiagnosticName:  'check'
  Message:         'error'
  FileOffset:      1
  FilePath:        'path/to/file'
'''

  has_errors_json = [{
      "FileOffset": 1,
      "DiagnosticName": "check",
      "Message": "error",
      "FilePath": "path/to/file"
  }]

  yield (api.test('with_errors') + api.properties(
      patch_project='fuchsia',
      patch_gerrit_url='https://fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      paths=['path/to/file', 'other/path/to/file']) +
         api.step_data('clang-tidy.get changed files',
                       api.raw_io.stream_output(show_output)) + api.step_data(
                           'clang-tidy.path/to/file.load yaml',
                           stdout=api.json.output('')) + api.step_data(
                               'clang-tidy.other/path/to/file.load yaml',
                               stdout=api.json.output(has_errors_json)))

  yield (api.test('no_errors') + api.properties(
      patch_project='fuchsia',
      patch_gerrit_url='https://fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      paths=['path/to/file', 'other/path/to/file']) +
         api.step_data('clang-tidy.get changed files',
                       api.raw_io.stream_output(show_output)) + api.step_data(
                           'clang-tidy.path/to/file.load yaml',
                           stdout=api.json.output('')) + api.step_data(
                               'clang-tidy.other/path/to/file.load yaml',
                               stdout=api.json.output('')))
