# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for running Tricium clang-format analyzer."""

from contextlib import contextmanager

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/cipd',
    'infra/git',
    'infra/jiri',
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
    'project': Property(kind=str, help='Project name', default=None),
    'manifest': Property(kind=str, help='Jiri manifest to use', default=None),
}


def RunSteps(api, project, manifest):
  if manifest:
    api.jiri.ensure_jiri()
    api.jiri.init()
    api.jiri.import_manifest(
        manifest,
        api.tricium.repository,
        name=project,
        revision=api.tricium.ref)
    api.jiri.update(run_hooks=False)
  else:
    api.git.checkout(api.tricium.repository, ref=api.tricium.ref)

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

  with api.context(cwd=api.path['start_dir'].join(project)):
    diff_step = api.git(
        'diff',
        '--name-only',
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

  yield (api.test('manifest') + api.properties(
      manifest='manifest/topaz',
      project='topaz',
      repository='https://fuchsia.googlesource.com/topaz',
      ref='HEAD',
      paths=['path/to/file', 'other/path/to/file']) + api.step_data(
          'check file formatting', api.raw_io.stream_output(diff_output)))

  yield (api.test('git') + api.properties(
      project='tools',
      repository='https://fuchsia.googlesource.com/tools',
      ref='HEAD',
      paths=['path/to/file', 'other/path/to/file']) + api.step_data(
          'check file formatting', api.raw_io.stream_output(diff_output)))
