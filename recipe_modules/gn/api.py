# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class GNApi(recipe_api.RecipeApi):
  """APIs for interacting with build systems.

  Clients must call set_path before using this module, to point to the prebuilt GN binary.
  """

  def __init__(self, *args, **kwargs):
    super(GNApi, self).__init__(*args, **kwargs)
    self._exe = None

  def __call__(self, *args, **kwargs):
    assert self._exe, "missing executable. Did you call set_path?"
    name = kwargs.pop('name', 'gn ' + args[0])
    cmd = [self._exe]
    return self.m.step(name, cmd + list(args or []), **kwargs)

  def set_path(self, path):
    """Sets the path to the GN executable."""
    self._exe = path