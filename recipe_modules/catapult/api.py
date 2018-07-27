# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class CatapultApi(recipe_api.RecipeApi):
  """CatapultApi provides support for the Catapult infra tool."""

  def __init__(self, *args, **kwargs):
    super(CatapultApi, self).__init__(*args, **kwargs)
    self._catapult = None

  def __call__(self, *args, **kwargs):
    """Return a catapult command step."""
    assert self._catapult

    subcommand = args[0]  # E.g. 'make_histogram' or 'update'
    flags = list(args[1:])
    full_cmd = [self._catapult, subcommand] + flags

    name = kwargs.pop('name', 'catapult ' + subcommand)
    return self.m.step(name, full_cmd, **kwargs)

  def ensure_catapult(self, version=None):
    with self.m.step.nest('ensure_catapult'):
      with self.m.context(infra_steps=True):
        catapult_package = (
            'fuchsia/infra/catapult/%s' % self.m.cipd.platform_suffix())
        cipd_dir = self.m.path['start_dir'].join('cipd', 'catapult')

        self.m.cipd.ensure(cipd_dir, {catapult_package: version or 'latest'})
        self._catapult = cipd_dir.join('catapult')

        return self._catapult

  def upload(self, input_file, url, timeout=None, **kwargs):
    """
    Uploads performance JSON data to a dashboard.

    Args:
      input_file (Path): Full path to the input file to upload.
      url (string): The url to upload data to.
      timeout (string): Optional request timeout duration string. e.g. 12s or
        1m.
      kwargs: Keyword argments passed to the returned step.

    Returns:
      A step to execute the upload subcommand.
    """
    args = ['upload', '-url', url]
    if timeout:
      args += ['-timeout', timeout]
    args.append(input_file)

    return self(*args, **kwargs)
