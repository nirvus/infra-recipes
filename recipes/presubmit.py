# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for running generic presubmit checks on git repos."""

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/checkout',
    'infra/git',
    'infra/jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = {
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use', default=None),
    'remote':
        Property(kind=str, help='Remote manifest repository', default=None),
}

# Arbitrarily chosen IO timeout in seconds.
IO_TIMEOUT_SECS = 300


def RunSteps(api, project, manifest, remote):
  # This recipe is only intended to run as a blocker for submitting code, not validation
  # on CI.
  assert api.properties.get('tryjob')

  # Checkout the current patchset while asserting there's only one item in the list.
  [gerrit_change] = api.buildbucket.build.input.gerrit_changes

  # TODO(kjharland): Ensure and Init Jiri inside CheckoutApi.
  api.jiri.ensure_jiri()
  api.jiri.init()

  # Checkout the given change.
  api.checkout.from_patchset(
      manifest=manifest,
      remote=remote,
      project=project,
      run_hooks=True,
      timeout_secs=IO_TIMEOUT_SECS,
      gerrit_change=gerrit_change,
  )

  # Run presubmit checks.
  ensure_no_patchfile(api, gerrit_change.project)


def ensure_no_patchfile(api, project):
  default_path = api.path['start_dir'].join(project, '.patchfile')
  if api.path.exists(default_path):
    raise api.step.StepFailure(
        'Cannot check in .patchfile, found at %s' % default_path)


def GenTests(api):
  project = 'garnet'
  manifest = 'garnet/garnet'
  remote = 'https://fuchsia.googlesource.com/garnet'

  #TODO(IN-776): Use upstream buildbucket test data.
  buildbucket_properties = dict()
  buildbucket_properties['$recipe_engine/buildbucket'] = {
      'build': {
          'builder': {
              'bucket': 'test-bucket'
          },
          'id': '5555555555',
          'project': project,
          'tags': ['builder:test-builder'],
          'input': {
              'gerrit_changes': [{
                  'host': 'fuchsia-review.googlesource.com',
                  'project': project,
                  'change': 100,
                  'patchset': 5,
              }],
          },
      },
  }

  #yapf:disable
  yield (api.test('when_patchfile_is_present') +
         api.path.exists(api.path['start_dir'].join(project, '.patchfile')) +
         api.step.step_data('read .patchfile', api.json.output([{
           'ref': 'refs/changes/ff/ddeeff/2',
           'host': 'fuchsia-review.googlesource.com',
           'project': 'zircon',
         }])) +
         api.properties(
           manifest=manifest,
           project=project,
           remote=remote,
           tryjob=True,
           **buildbucket_properties))

  yield (api.test('when_patchfile_is_missing') +
         api.properties(
           manifest=manifest,
           project=project,
           remote=remote,
           tryjob=True,
           **buildbucket_properties))
  #yapf:enable
