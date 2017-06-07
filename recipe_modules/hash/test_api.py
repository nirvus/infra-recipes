# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class HashTestApi(recipe_test_api.RecipeTestApi):

  def __call__(self, digest=''):
    return self.m.raw_io.stream_output(digest)
