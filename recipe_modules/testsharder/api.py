# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Recipe module that wraps the testsharder tool, which searches a Fuchsia
build for test specifications and groups them into shards.

The tool accepts a platforms file, which it uses for policy checking, and
assigns a unique name to each produced shard.

Platforms file definition:
https://fuchsia.googlesource.com/infra/infra/+/master/fuchsia/testexec/test_platforms.go

Testsharder tool:
https://fuchsia.googlesource.com/infra/infra/+/master/cmd/testsharder/
"""

from recipe_engine import recipe_api


class Test(object):
  """Represents a test binary which tests Fuchsia."""

  @staticmethod
  def from_json(jsond):
    """Creates a new Test from a JSON-compatible dict."""
    return Test(
        name=jsond.get('name', ''),
        location=jsond['location'])

  def __init__(self, name, location):
    """Initializes a Test.

    Args:
      name (str): The name of the test.
      location (str): The location of the test on a running Fuchsia instance.
    """
    self.name = name
    self.location = location

  def render_to_json(self):
    """Returns a JSON-compatible dict representing the Test.

    The format follows the format found here:
    https://fuchsia.googlesource.com/infra/infra/+/master/fuchsia/testexec/shard.go
    """
    return {
        'name': self.name,
        'location': self.location,
    }

class Shard(object):
  """Represents a shard of several tests with one common environment."""

  @staticmethod
  def from_json(jsond):
    """Creates a new Shard from a JSON-compatible Python dict."""
    return Shard(
        name=jsond['name'],
        tests=[Test.from_json(test) for test in jsond['tests']],
        device_type=jsond['environment']['device']['type'])

  def __init__(self, name, tests, device_type):
    """Initializes a Shard.

    Args:
      name (str): The name of the shard.
      tests (seq[Test]): A sequence of tests.
      device_type (str): The type of device which the tests will run on.
    """
    self.name = name
    self.tests = tests
    self.device_type = device_type

  def render_to_json(self):
    """Returns a JSON-compatible dict representing the Shard.

    The format follows the format found here:
    https://fuchsia.googlesource.com/infra/infra/+/master/fuchsia/testexec/shard.go
    """
    return {
        'name': self.name,
        'tests': [test.render_to_json() for test in self.tests],
        'environment': {'device': {'type': self.device_type}},
    }


class TestsharderApi(recipe_api.RecipeApi):
  """Module for interacting with the Testsharder tool.

  The testsharder tool accepts a set of test specifications and produces
  a file containing shards of execution.
  """
  def __init__(self, *args, **kwargs):
    super(TestsharderApi, self).__init__(*args, **kwargs)
    self._testsharder_path = None

  def ensure_testsharder(self, version='latest'):
    with self.m.step.nest('ensure_testsharder'):
      with self.m.context(infra_steps=True):
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('fuchsia/infra/testsharder/${platform}', version)
        cipd_dir = self.m.path['start_dir'].join('cipd', 'testsharder')
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._testsharder_path = cipd_dir.join('testsharder')
        return self._testsharder_path

  def execute(self,
               step_name,
               # TODO(IN-575): Consider removing target_arch and platforms_file
               # in favor of relying on future build-time policy checks.
               target_arch,
               platforms_file,
               fuchsia_build_dir,
               output_file=None,
               shard_prefix=None):
    """Executes the testsharder tool.

    Args:
      step_name (str): name of the step.
      target_arch (str): the target architecture which Fuchsia tests were built
        for.
      platforms_file (Path): path to a file containing the set of valid
        platforms for testing Fuchsia. See
        https://fuchsia.googlesource.com/infra/infra/+/master/fuchsia/testexec/test_platforms.go
      fuchsia_build_dir (Path): path to a Fuchsia build output directory for
        which GN has been run (ninja need not have been executed).
      output_file (Path): optional file path to leak output to.
      shard_prefix (str): optional prefix for shard names.

    Returns:
      A list of Shards, each representing one test shard.
    """
    assert self._testsharder_path
    cmd = [
        self._testsharder_path,
        '-target-arch', target_arch,
        '-platforms-file', platforms_file,
        '-fuchsia-build-dir', fuchsia_build_dir,
        '-output-file', self.m.json.output(leak_to=output_file),
    ]
    if shard_prefix:
      cmd.extend(['-shard-prefix', shard_prefix])
    result = self.m.step(step_name, cmd).json.output
    return [Shard.from_json(shard) for shard in result['shards']]
