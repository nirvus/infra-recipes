# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class IsolatedTestApi(recipe_test_api.RecipeTestApi):

  def archive(self):
    return self.m.raw_io.output_text('[dummy hash]')
