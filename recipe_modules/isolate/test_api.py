# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

import os


class SwarmingTestApi(recipe_test_api.RecipeTestApi):

  def archive(self, isolated):
    name = os.path.basename(str(isolated)).rsplit(".", 1)[0]
    return self.m.json.output({name: '[dummy hash]'})
