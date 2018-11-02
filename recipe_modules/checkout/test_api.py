# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CheckoutTestApi(recipe_test_api.RecipeTestApi):

  def buildbucket_properties(self,
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
    input = self.gitiles_commit(project)
    if tryjob:
      input = self.gerrit_changes(project)

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

  def gerrit_changes(self, project):
    return {
        'gerrit_changes': [{
            'host': 'fuchsia-review.googlesource.com',
            'project': project,
            'change': 100,
            'patchset': 5,
        },]
    }

  def gitiles_commit(self, project):
    return {
        'gitiles_commit': {
            'host': 'fuchsia.googlesource.com',
            'project': project,
            'ref': 'refs/heads/master',
            'id': 'a1b2c3',
        }
    }
