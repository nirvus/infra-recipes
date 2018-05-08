# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

class JiriTestApi(recipe_test_api.RecipeTestApi):
  @staticmethod
  def read_manifest_element(api, manifest, element_type, element_name, test_output):
    """Simulates a call to JiriApi.read_manifest_element.

    Use this in-favor of creating testing step data directly in a test case.  It
    prevents the need for a test_data= parameter JiriApi.read_manfiest_element,
    the need to put test code inline with production code, and the need to
    understand how the returned step provides output (via step_result.sdout,
    step_result.json.output, etc).  Calling this is like "injecting a step" into
    the execution pipeline.

    Args:
      api (RecipeTestApi): The test api.
      test_output (Dict): The data to use as JSON in the step's stdout response.

      (See JiriApi for docs on remaining args)

    Returns:
      recipe_test_api.TestData simulating a step to read data from a manifest.
    """
    # `manifest` and `element_type` are not used by this method.  Including them
    # as parameters is intentionally done for parity between this method's and
    # JiriApi.read_manifest_element's signatures.

    step_name = 'read_manifest_%s.jiri manifest' % element_name
    step_output = api.json.output(test_output)
    return api.step_data(step_name, stdout=step_output)

  @property
  def read_manifest_project_output(self):
      """A dict simulating output of reading a <project> from a manifest."""
      return {
          'gerrithost': 'project_gerrit_host',
          'githooks': 'project_githooks',
          'historydepth': 'project_historydepth',
          'name': 'project_name',
          'path': 'project_path',
          'remote': 'project_remote',
          'revision': 'project_revision',
      }

  @property
  def example_revision(self):  # pragma: no cover
    return 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127'

  @property
  def example_snapshot(self):
    return '''<manifest>
  <projects>
    <project name="manifest" path="manifest" remote="https://fuchsia.googlesource.com/manifest" revision="4c2b0da3c06341db5cebe4d02c78c93c3b2bd78b"/>
  </projects>
</manifest>'''

  @property
  def example_source_manifest(self):
    return {
        'directories': {
            'manifest': {
                'git_checkout': {
                    'repo_url': 'https://fuchsia.googlesource.com/manifest',
                    'revision': '4c2b0da3c06341db5cebe4d02c78c93c3b2bd78b',
                }
            }
        }
    }

  def example_edit(self, imports, projects):
    """Creates example JSON output for the Jiri edit subcommand.

    The data returned by this command is similar to the data generated when
    `Jiri edit` is invoked with the -json-output flag.

    Args:
      imports (List(tuple)): A list of (name, revision) tuples representing
         imports to update in the manifest.
      projects (List(tuple)): A list of (name, revision) tuples representing
         projects to update in the manifest.

    Returns:
      A dict representing JSON that matches the output of the Jiri edit
      subcommand. The dict has the following structure:

        {
          'imports': [
            {
              'name': ...
              'remote': ...
              'old_revision': ...
              'new_revision': ...
            },
            ...
          ],
          'projects': [
            {
              'name': ...
              'remote': ...
              'path: ...
              'old_revision': ...
              'new_revision': ...
            },
            ...
          ],
        }

      Where each entry in imports and projects is a dict representing an edit to
      an import or project, respectively.
    """
    project_edits = []
    for project in projects:
      name, revision = project
      project_edits.append({
          'name': name,
          'remote': 'http://example.com',
          'path': '/path/to/' + name,
          'old_revision': '[OLD_REVISION]',
          'new_revision': revision,
      })

    import_edits = []
    for imp in imports:
      name, revision = imp
      import_edits.append({
          'name': name,
          'remote': 'http://example.com',
          'old_revision': '[OLD_REVISION]',
          'new_revision': revision,
      })

    return {'projects': project_edits, 'imports': import_edits}

  def project(self, projects):
    """Provides test mock for the `project` method."""
    assert projects is not None
    return self.m.json.output(projects)

  def snapshot(self, data):
    """Provides test mock for the `snapshot` method."""
    assert data is not None
    return self.m.raw_io.output(data, name='snapshot')

  def source_manifest(self, data):
    """Provides test mock for the `source_manifest` method."""
    assert data is not None
    return self.m.json.output(data, name='source manifest')
