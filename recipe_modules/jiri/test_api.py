# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class JiriTestApi(recipe_test_api.RecipeTestApi):

  @property
  def example_revision(self): # pragma: no cover
    return 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127'

  @property
  def example_edit(self):
    return {
      'imports': [
        {
          'old_revision': 'A',
          'new_revision': 'B',
        },
      ],
    }

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
