# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for running Tricium clang-format analyzer."""

from contextlib import contextmanager

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/cipd',
    'infra/fuchsia',
    'infra/git',
    'infra/goma',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/tricium',
]

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

PROPERTIES = {
    'repository':
        Property(kind=str, help='Repository to checkout', default=None),
    'ref':
        Property(kind=str, help='Gerrit patch ref', default=None),
    'manifest':
        Property(
            kind=str, help='Jiri manifest to use', default="manifest/minimal"),
}


def RunSteps(api, repository, ref, manifest):
  api.goma.ensure_goma()

  api.fuchsia.checkout(
      manifest=manifest,
      remote=repository,
      patch_ref=ref,
  )

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
          'fuchsia/clang/${platform}': 'goma',
      })

  cmd = [cipd_dir.join('bin', 'clang-format'), '-i']
  for changed_file in api.tricium.paths:
    cmd.append(api.path['start_dir'].join(changed_file))

  format_step = api.step('clang-format', cmd)

  diff_step = api.git(
      'diff',
      '--names-only',
      name='check file formatting',
      stdout=api.raw_io.output())

  if diff_step.stdout:
    files = diff_step.stdout.split('\n')
    for formatted_file in files:
      api.tricium.add_comment(
          'ClangFormat/Unformatted',
          'File not formatted properly.\nRun the following to format:\n\nclang-format -i %s'
          % formatted_file, formatted_file)

  api.tricium.write_comments()


def GenTests(api):
  diff_output = '''path/to/file
other/path/to/file'''

  yield (api.test('default') + api.properties(
      repository='https://fuchsia.googlesource.com/topaz',
      ref='ref/changes/99/999999/9',
      paths=['path/to/file', 'other/path/to/file']) + api.step_data(
          'check file formatting', api.raw_io.stream_output(diff_output)))
