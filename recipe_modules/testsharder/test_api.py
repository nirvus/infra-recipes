# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from .api import Shard, Test


class TestsharderTestApi(recipe_test_api.RecipeTestApi):
  def shard(self, *args, **kwargs):
    """Creates a Shard object representing a shard."""
    return Shard(*args, **kwargs)

  def test(self, *args, **kwargs):
    """Creates a Test object representing a test."""
    return Test(*args, **kwargs)

  def execute(self, step_name, shards):
    """Mocks the result from a call to execute.

    Args:
      step_name (str): The name of the step to mock.
      shards (seq[Shard]): A sequence of Shard objects that will be mocked in
        as the result for an execute call.
    """
    return self.step_data(step_name, self.m.json.output({
        'shards': [shard.render_to_json() for shard in shards]}))
