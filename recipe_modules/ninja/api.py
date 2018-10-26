# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class NinjaApi(recipe_api.RecipeApi):
  """APIs for interacting with Ninja.

  Clients must call set_path before using this module, to point to the prebuilt Ninja
  binary.
  """

  def __init__(self, *args, **kwargs):
    super(NinjaApi, self).__init__(*args, **kwargs)
    self._exe = None

  def __call__(self,
               build_dir,
               targets,
               job_count=None,
               build_file=None,
               fail_threshold=None,
               verbose=False):
    """Runs Ninja.

    Args:
      build_dir (Path): CD into this directory before executing.
      job_count (int): No. parallel jobs (Ninja default is to guess from available CPUs).
      targets (List(string)): List of targets to build.
      build_file (Path): Ninja build file (default=build.ninja)
      fail_threshold (int): Keep going until this many jobs fail (Ninja default of 1).
      verbose (bool): Show all command lines when building.

    Returns:
      The step result of running Ninja.
    """
    assert self._exe, "missing executable. Did you call set_path?"

    args = [
        self._exe,
        '-C',
        build_dir,
    ]

    if job_count:
      args.extend(['-j', job_count])
    if build_file:
      args.extend(['-f', build_file])
    if fail_threshold:
      args.extend(['-k', fail_threshold])
    if verbose:
      args.append('-v')

    args.extend(targets)

    return self.m.step('ninja', args)

  def set_path(self, path):
    """Sets the path to the Ninja executable."""
    self._exe = path
