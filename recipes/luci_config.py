# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for testing LUCI configs."""

import difflib
from recipe_engine.recipe_api import Property

DEPS = [
    'infra/jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = {
    'config_project':
        Property(
            kind=str,
            help='Jiri remote manifest project containing the luci configs',
            default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
}

_PREBUILT_PROJECT_REMOTE = 'https://fuchsia.googlesource.com/infra/prebuilt'


def RunSteps(api, config_project, manifest, remote):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(
        manifest=manifest,
        remote=remote,
        build_input=api.buildbucket.build.input)

  # Find the required jiri projects.
  config_jiri_project, prebuilt_jiri_project = None, None
  jiri_projects = api.jiri.project()
  for jiri_project in jiri_projects.json.output:
    if jiri_project['name'] == config_project:
      config_jiri_project = jiri_project
    if jiri_project['remote'] == _PREBUILT_PROJECT_REMOTE:
      prebuilt_jiri_project = jiri_project
  assert config_jiri_project, 'Failed to find project %s' % config_project
  assert prebuilt_jiri_project, (
      'Failed to find project with remote %s' % _PREBUILT_PROJECT_REMOTE)

  # Needs to be kept in sync with //infra/prebuilt/tools/cipd.ensure.
  flatten_buildbucket_path = api.path['start_dir'].join(
      prebuilt_jiri_project['path'], 'tools', 'flatten_buildbucket_cfg',
      'flatten_buildbucket_cfg')

  services_path = api.path['start_dir'].join(config_jiri_project['path'],
                                             'config', 'services')
  buildbucket_config_paths = api.file.glob_paths(
      name='glob buildbucket configs',
      source=services_path,
      pattern='*buildbucket*.cfg')
  if not buildbucket_config_paths:
    raise api.step.StepFailure(
        'Found no buildbucket configs under %s' % services_path)


  for buildbucket_config_path in buildbucket_config_paths:
    # Flatten the existing config. Fails if it is not a valid config proto.
    basename = api.path.basename(buildbucket_config_path)
    flatten_step = api.step(
        'flatten %s' % basename,
        [flatten_buildbucket_path, buildbucket_config_path],
        stdout=api.raw_io.output_text())
    flattened_config = flatten_step.stdout

    # Compare the flattened to the copy in generated/ sub-dir. This enforces
    # that the generated copy stays up to date.
    expected_config = api.file.read_text(
        'read generated/%s' % basename, services_path.join(
            'generated', basename))
    with api.step.nest('diff %s' % basename):
      expected_lines = expected_config.split('\n')
      flattened_lines = flattened_config.split('\n')
      diff = list(
          difflib.context_diff(
              expected_lines,
              flattened_lines,
              fromfile='generated/%s' % basename,
              tofile='%s.flattened' % basename))
      if diff:
        api.step.active_result.presentation.logs['diff'] = diff
        api.step.active_result.presentation.logs['expected'] = expected_lines
        api.step.active_result.presentation.logs['flattened'] = flattened_lines
        raise api.step.StepFailure('Found diff')
      api.step.active_result.presentation.step_text = 'no diff'


def GenTests(api):
  properties = api.properties(
      config_project='fuchsia-infra/config',
      manifest='manifest/infra',
      remote='https://fuchsia.googlesource.com/manifest',
  )
  jiri_projects = api.step_data(
      'jiri project',
      api.jiri.project([{
          'name': 'fuchsia-infra/config',
          'path': 'config',
          'remote': 'https://fuchsia.googlesource.com/infra/config'
      }, {
          'name': 'prebuilt',
          'path': 'fuchsia-infra/prebuilt',
          'remote': 'https://fuchsia.googlesource.com/infra/prebuilt'
      }]))
  glob_step_data = api.step_data(
      'glob buildbucket configs',
      api.file.glob_paths(names=('cr-buildbucket.cfg',)))

  yield (api.test('no_diff') + properties + jiri_projects + glob_step_data +
         api.step_data(
             'flatten cr-buildbucket.cfg',
             stdout=api.raw_io.output_text('foo\nbar\n')) + api.step_data(
                 'read generated/cr-buildbucket.cfg',
                 api.file.read_text(text_content='foo\nbar\n')))

  yield (api.test('diff') + properties + jiri_projects + glob_step_data +
         api.step_data(
             'flatten cr-buildbucket.cfg',
             stdout=api.raw_io.output_text('foo\nbaz\n')) + api.step_data(
                 'read generated/cr-buildbucket.cfg',
                 api.file.read_text(text_content='foo\nbar\n')))

  yield (api.test('no_buildbucket_configs') + properties + jiri_projects +
         api.step_data('glob buildbucket configs', api.file.glob_paths()))
