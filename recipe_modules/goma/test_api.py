# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GomaTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, goma_dir=None, jobs=None, deps_cache=None,
               local_output_cache=None):
    """Simulate pre-configured Goma through properties."""
    assert not jobs or isinstance(jobs, int)
    assert not deps_cache or isinstance(deps_cache, bool)
    assert not local_output_cache or isinstance(local_output_cache, bool)
    ret = self.test(None)
    ret.properties = {
      '$infra/goma': {}
    }
    if goma_dir:
      ret.properties['$infra/goma'].update({
          'goma_dir': goma_dir,
      })
    if jobs:
      ret.properties['$infra/goma'].update({
          'jobs': jobs,
      })
    if deps_cache:
      ret.properties['$infra/goma'].update({
          'deps_cache': deps_cache,
      })
    if local_output_cache:
      ret.properties['$infra/goma'].update({
          'local_output_cache': local_output_cache,
      })
    return ret
