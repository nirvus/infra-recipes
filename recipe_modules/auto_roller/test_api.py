# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class AutoRollerTestApi(recipe_test_api.RecipeTestApi):

  def success(self):
    """Returns mock data indicating a successful roll."""
    return self.m.json.output({
      'status': 'MERGED',
      'labels': {'Commit-Queue': {'approved':{}}}
    })

  def failure(self):
    """Returns mock data indicating a CQ failure."""
    return self.m.json.output({
      'status': 'NEW',
      'labels': {'Commit-Queue': {}}
    })

  def dry_run(self):
    """Returns mock data indicating a dry run is complete."""
    # Note, this is the same output we expect on failure (CQ just
    # un-sets the CQ label).
    return self.failure()

  def timeout(self):
    """Returns mock data indicating a roller timeout."""
    return self.m.json.output({
        'status': 'NEW',
        'labels': {
            'Commit-Queue': {
                'approved': {}
            }
        }
    })
