# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CatapultTestApi(recipe_test_api.RecipeTestApi):

  @property
  def buildbucket_property_json(self):
    """Returns mock buildbucket data consumed by the CatapultApi.

    Use this as the value for api.properties(buildbucket=...) when testing.
    """
    return self.m.json.dumps({"build": {"url": "http://log.com/123"}})
