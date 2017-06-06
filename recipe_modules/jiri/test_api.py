# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class JiriTestApi(recipe_test_api.RecipeTestApi):

  @property
  def example_revision(self):
    return "c22471f4e3f842ae18dd9adec82ed9eb78ed1127"

  def example_project(self, projects):
    assert projects is not None
    return self.m.json.output([
      {
          "name": project,
          "path": "/path/to/repo",
          "remote": "https://fuchsia.googlesource.com/repo",
          "revision": self.example_revision,
          "current_branch": "",
          "branches": [
              "(HEAD detached at c22471f)",
              "master"
          ]
      }
      for project in projects
    ])

  def example_snapshot(self):
    return self.m.raw_io.output('''
<manifest>
  <projects>
    <project name="manifest" path="manifest" remote="https://fuchsia.googlesource.com/manifest" revision="4c2b0da3c06341db5cebe4d02c78c93c3b2bd78b"/>
  </projects>
</manifest>
''')
