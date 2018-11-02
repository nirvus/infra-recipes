# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CheckoutTestApi(recipe_test_api.RecipeTestApi):

  def test(self, name, project, patchfile=None, override=False, tryjob=False):
    """Creates a CheckoutApi test case

    Args:
        name (str): The name of this test case.
        project (str): The name of the git project being tested.
        patchfile (Dict): JSON object representing the contents of a patchfile.  If unset,
          no patchfile will be present in this test.
        override (bool): Whether to `jiri override` the project being tested.
        tryjob (bool): Whether this is a tryjob.
    """
    # Default properties.
    properties = dict(
        project=project,
        override=override,
    )

    # Add buildbucket properties.
    properties.update(
        self._buildbucket_properties(
            project=project,
            tryjob=tryjob,
        ))

    # Create return value.
    ret = super(CheckoutTestApi, self).test(name)

    # Add test patchfile if specified.
    if patchfile is not None:
      patchfile_path = self.m.path['start_dir'].join(project, '.patchfile')
      ret += self.m.path.exists(patchfile_path)
      ret += self.step_data('read .patchfile', self.m.json.output(patchfile))

    if tryjob:
      ret += self.m.properties.tryserver(**properties)
    else:
      ret += self.m.properties(**properties)

    return ret

  def _buildbucket_properties(self,
                              bucket='###buildbucket-bucket###',
                              builder='###buildbucket-builder###',
                              project='###buildbucket-project###',
                              tryjob=False):
    """Returns input Recipe property json that would normally be specified as
        $recipe_engine/buildbucket properties.  These should be passed as test properties:

        Example:
            props = {
                '$recipe_engine/buildbucket': self.m.checkout.buildbucket_properties()
            }

            self.m.properties(**props)
        """
    input = self._gitiles_commit(project)
    if tryjob:
      input = self._gerrit_changes(project)

    return {
        '$recipe_engine/buildbucket': {
            'build': {
                'builder': {
                    'bucket': bucket,
                },
                'id': '5555555555',
                'project': project,
                'tags': ['builder:%s' % builder],
                'input': input
            },
        }
    }

  def _gerrit_changes(self, project):
    return {
        'gerrit_changes': [{
            'host': 'fuchsia-review.googlesource.com',
            'project': project,
            'change': 100,
            'patchset': 5,
        },]
    }

  def _gitiles_commit(self, project):
    return {
        'gitiles_commit': {
            'host': 'fuchsia.googlesource.com',
            'project': project,
            'ref': 'refs/heads/master',
            'id': 'a1b2c3',
        }
    }
