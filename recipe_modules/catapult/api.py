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

  def make_histogram(self, input_file, test_suite, builder, bucket, datetime):
    """
    Generates a HistogramSet from performance test output.

    Args:
      test_suite (string): The name of the test suite
      builder (string): The name of the current builder
      bucket (string): The name of the builder's bucket
      datetime (uint): Ms since epoch when tests were executed.
      input_file (string): Full path to the input file containing test results.

    Returns:
      A step to execute the make_histogram subcommand.
    """
    return self(
        'make_histogram',
        '-test-suite',
        test_suite,
        '-builder',
        builder,
        '-bucket',
        bucket,
        '-datetime',
        datetime,
        input_file,
    )

  def upload(self, input_file, service_account_json, url, timeout):
    """
    Uploads performance JSON data to a dashboard.

    Args:
      service_account_json (string): Full path to a service account credentials
          file.
      url (string): The url to upload data to.
      timeout (string): Request timeout duration string. e.g. 12s or 1m.

    Returns:
      A step to execute the upload subcommand.
    """
    return self(
        'upload',
        '-service-account-json',
        service_account_json,
        '-url',
        url,
        '-timeout',
        timeout,
        input_file,
    )
