# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class LkgsApi(recipe_api.RecipeApi):
  """APIs for deriving the last-known-good-snapshot for a builder."""

  def __init__(self, *args, **kwargs):
    super(LkgsApi, self).__init__(*args, **kwargs)
    self._lkgs_tool = None

  def __call__(self, step_name, builder, output_file):
    """Retrieves the last-known-"good"-(jiri-)snapshot given a builder.

    Args:
      step_name (str): The name of the step produced.
      builder (seq[str]): A list of fully-qualified buildbucket v2 builder ID,
        consisting of <project>/<project-namespaced bucket>/<builder name>. For example:
        ['fuchsia/ci/garnet-x64-release-qemu_kvm'].
      output_file (Path|Placeholder): The location to dump the retrieved
        snapshot.
    """
    assert self._lkgs_tool

    step_args = [
        self._lkgs_tool,
        '-output-file',
        output_file,
    ]

    for b in builder:
      step_args += [
          '-builder-id',
          b,
      ]

    return self.m.step(step_name, step_args)

  def ensure_lkgs(self, version=None):
    """Ensures that the lkgs tool is installed."""
    with self.m.step.nest('ensure_lkgs'):
      with self.m.context(infra_steps=True):
        lkgs_package = ('fuchsia/infra/lkgs/%s' % self.m.cipd.platform_suffix())
        cipd_dir = self.m.path['start_dir'].join('cipd', 'lkgs')

        self.m.cipd.ensure(cipd_dir, {lkgs_package: version or 'release'})
        self._lkgs_tool = cipd_dir.join('lkgs')

        return self._lkgs_tool

  @property
  def lkgs_tool(self):
    return self._lkgs_tool
