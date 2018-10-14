# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class BuildSetLookupApi(recipe_api.RecipeApi):
  """APIs for retrieving the build ID for a given buildset and builder ID."""

  def __init__(self, *args, **kwargs):
    super(BuildSetLookupApi, self).__init__(*args, **kwargs)
    self._buildset_lookup_tool = None

  def __call__(self, step_name, builder, buildset, leak_to=None):
    """Retrieves the build ID for a given buildset and builder ID.

    Args:
      step_name (str): The name of the step produced.
      builder (str): A fully-qualified buildbucket v2 builder ID,
        consisting of <project>/<project-namespaced bucket>/<builder name>. For example:
        'fuchsia/ci/garnet-x64-release-qemu_kvm'.
      buildset (str): A fully-qualified buildbucket V2 buildset tag,
        consisting of commit/gitiles/<host>/<repo>/+/<commit ID>.  For example:
        'commit/gitiles/fuchsia.googlesource.com/topaz/+/e3127e0bd6d57da7a5959ee70eb0a396590e6d53'.
      leak_to (Path): If leak_to is provided, it must be a Path object. This path will be used in
        place of a random temporary file, and the file will not be deleted at the end of the step.
    """
    assert self._buildset_lookup_tool

    step_args = [
        self._buildset_lookup_tool,
        '-builder-id',
        builder,
        '-build-set',
        buildset,
    ]

    return self.m.step(
        step_name, step_args, stdout=self.m.raw_io.output(leak_to=leak_to))

  def ensure_buildset_lookup(self, version=None):
    """Ensures that the buildset lookup tool is installed."""
    with self.m.step.nest('ensure_buildset_lookup'):
      with self.m.context(infra_steps=True):
        buildset_lookup_package = (
            'fuchsia/infra/buildsetlookup/%s' % self.m.cipd.platform_suffix())
        cipd_dir = self.m.path['start_dir'].join('cipd', 'buildsetlookup')

        self.m.cipd.ensure(cipd_dir,
                           {buildset_lookup_package: version or 'latest'})
        self._buildset_lookup_tool = cipd_dir.join('buildsetlookup')

        return self._buildset_lookup_tool

  @property
  def buildset_lookup_tool(self):
    return self._buildset_lookup_tool
