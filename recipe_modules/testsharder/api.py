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
        testsharder_package = (
            'fuchsia/infra/testsharder/%s' % self.m.cipd.platform_suffix())
        testsharder_dir = self.m.path['start_dir'].join('cipd', 'testsharder')

        self.m.cipd.ensure(testsharder_dir,
                           {testsharder_package: version})
        self._testsharder_path = testsharder_dir.join('testsharder')

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
      A dict representing a JSON-encoded set of shards. The format for said
      shards may be found here:
      https://fuchsia.googlesource.com/infra/infra/+/master/fuchsia/testexec/shard.go
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
    return self.m.step(step_name, cmd).json.output
