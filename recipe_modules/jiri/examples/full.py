# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'jiri',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def RunSteps(api):
  # First, ensure we have jiri.
  api.jiri.ensure_jiri()
  assert api.jiri.jiri

  api.jiri.checkout(
      'minimal',
      'https://fuchsia.googlesource.com',
      patch_ref='refs/changes/1/2/3',
      patch_gerrit_url='https://fuchsia-review.googlesource.com')

  # Setup a new jiri root.
  api.jiri.init('dir')

  # Import the manifest.
  api.jiri.import_manifest(
      'minimal',
      'https://fuchsia.googlesource.com',
      name='manifest',
      overwrite=True)

  # Download all projects.
  api.jiri.update(gc=True, snapshot='snapshot', local_manifest=True)

  # Edit manifest.
  api.jiri.edit_manifest(
      'minimal',
      projects=['a', ('b', 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127')],
      imports=['c', ('d', 'fc4dc762688d2263b254208f444f5c0a4b91bc07')])

  # Read a project from the manifest
  project_dict = api.jiri.read_manifest_element(
      manifest='minimal',
      element_name="third_party/go",
  )
  # For the sake of testing, assert all values are filled in if the project was
  # found.
  if project_dict.get('name'):
    assert project_dict == {
        'gerrithost': 'project_gerrit_host',
        'githooks': 'project_githooks',
        'historydepth': 'project_historydepth',
        'name': 'project_name',
        'path': 'project_path',
        'remote': 'project_remote',
        'revision': 'project_revision',
    }
  else:
    # Otherwise just assert no info was found and the dict is empty.
    assert project_dict == {}

  # Run hooks separately.
  api.jiri.update(rebase_tracked=True, run_hooks=False)
  api.jiri.run_hooks(local_manifest=True)

  # Take a snapshot.
  api.jiri.snapshot()

  # Emit source manifest.
  api.jiri.source_manifest()

  # Get information about the project.
  api.jiri.project(['test'])

  # Patch in an existing change.
  api.jiri.patch(
      'refs/changes/1/2/3',
      host='https://fuchsia-review.googlesource.com',
      project='test',
      delete=True,
      force=True)

  # Clean up after ourselves.
  api.jiri.clean(all=True)


def GenTests(api):
  yield (api.test('basic') + api.step_data(
      'jiri manifest',
      stdout=api.json.output(
          api.json.dumps(api.jiri.read_manifest_project_output))))
  yield (api.test('missing_manifest_data') + api.step_data(
      'jiri manifest', stdout=api.json.output(api.json.dumps({}))))
