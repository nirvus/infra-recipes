# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GomaTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, jobs):
    """Simulate pre-configured Goma through properties."""
    assert isinstance(jobs, int), '%r (%s)' % (jobs, type(jobs))
    ret = self.test(None)
    ret.properties = {
      '$infra/goma': {
        'jobs': jobs,
      },
    }
    return ret
