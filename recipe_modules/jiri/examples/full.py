# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


PROPERTIES = {
    'tryjob': Property(kind=bool, help='', default=False),
    'checkout_from_snapshot':
        Property(kind=bool, help='Checkout from snapshot', default=False),
}


def RunSteps(api, tryjob, checkout_from_snapshot):
  # First, ensure we have jiri.
  api.jiri.ensure_jiri()
  assert api.jiri.jiri

  if checkout_from_snapshot:
    # Check out from snapshot.
    api.jiri.checkout_snapshot('snapshot')
  else:
    if tryjob:
      build_input = api.buildbucket.build_pb2.Build.Input(
          gerrit_changes=[
              api.buildbucket.common_pb2.GerritChange(
                  host='fuchsia-review.googlesource.com',
                  project='garnet',
                  change=100,
                  patchset=5,
              ),
          ],
      )
    else:
      build_input = api.buildbucket.build_pb2.Build.Input(
          gitiles_commit=api.buildbucket.common_pb2.GitilesCommit(
              host='fuchsia.googlesource.com',
              project='garnet',
              ref='refs/heads/master',
              id='a1b2c3',
          ),
      )
    api.jiri.checkout(
        manifest='minimal',
        remote='https://fuchsia.googlesource.com/manifest',
        build_input=build_input,
    )
  # Setup a new jiri root.
  api.jiri.init('dir')

  # Import the manifest.
  api.jiri.import_manifest(
      'minimal',
      'https://fuchsia.googlesource.com',
      name='manifest',
      revision='c22471f4e3f842ae18dd9adec82ed9eb78ed1127',
      overwrite=True
  )

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
      element_type='project',
      element_name='test/project',
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

  # Read an import from the manifest.
  element_dict = api.jiri.read_manifest_element(
      manifest='minimal',
      element_type='import',
      element_name='test/import',
  )
  # Just assert the dict is either empty or non-empty rather than repeat the
  # above checks with more mock data.
  if element_dict.get('name'):
    assert element_dict != {}
  else:
    assert element_dict == {}

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


# yapf: disable
def GenTests(api):
  yield (api.test('basic_ci') +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='import',
          element_name='test/import',
          test_output=api.jiri.read_manifest_project_output) +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='project',
          element_name='test/project',
          test_output=api.jiri.read_manifest_project_output))
  yield (api.test('basic_cq') +
      api.properties(tryjob=True) +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='import',
          element_name='test/import',
          test_output=api.jiri.read_manifest_project_output) +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='project',
          element_name='test/project',
          test_output=api.jiri.read_manifest_project_output))

  yield (api.test('checkout_from_snapshot') +
      api.properties(checkout_from_snapshot=True) +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='import',
          element_name='test/import',
          test_output=api.jiri.read_manifest_project_output) +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='project',
          element_name='test/project',
          test_output=api.jiri.read_manifest_project_output))

  yield (api.test('missing_manifest_project_data') +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='import',
          element_name='test/import',
          test_output={}) +
      api.jiri.read_manifest_element(api,
          manifest='minimal',
          element_type='project',
          element_name='test/project',
          test_output={}))
