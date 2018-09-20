# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class BazelApi(recipe_api.RecipeApi):
  """Provides steps to run bazel."""

  def __init__(self, *args, **kwargs):
    super(BazelApi, self).__init__(*args, **kwargs)
    self._bazel_path = None
    self._bazel_version = None

  def ensure_bazel(self, version='latest'):
    """Ensures that bazel is installed, returning its path.

    Additional calls with the same version are no-ops.
    Additional calls with a different version are errors.

    Args:
      version: The CIPD version to install.
    Returns:
      The Path to the bazel binary.
    Raises:
      AssertionError: if this method has already been called with a different
          version.
    """
    if self._bazel_path:
      assert version == self._bazel_version, (
          'Requested version "%s" but version "%s" has already been installed' %
          (version, self._bazel_version))
    if not self._bazel_path:
      with self.m.step.nest('ensure bazel'):
        with self.m.context(infra_steps=True):
          cipd_package = (
              'fuchsia/third_party/bazel/' + self.m.cipd.platform_suffix())
          cipd_root = self.m.path['start_dir'].join('cipd')

          self.m.cipd.ensure(cipd_root, {cipd_package: version})
          self._bazel_path = cipd_root.join('bazel')
          self._bazel_version = version

    return self._bazel_path

  # TODO(dbort): Add methods like build(), query() if clients will use them.
  # As of 2018-09, clients only need the path so they can pass it to SDK
  # testing scripts.
