# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import textwrap


class GoApi(recipe_api.RecipeApi):
  """GoApi provides support for Go."""

  def __init__(self, *args, **kwargs):
    super(GoApi, self).__init__(*args, **kwargs)
    self._go_dir = None

  def __call__(self, *args, **kwargs):
    """Return a Go command step."""
    assert self._go_dir

    name = kwargs.pop('name', 'go ' + args[0])
    new_env = self.m.context.env
    new_env.setdefault('GOROOT', self._go_dir)

    with self.m.context(env=new_env):
      go_cmd = [self.go_executable]
      return self.m.step(name, go_cmd + list(args or []), **kwargs)

  # Ensures Go is installed.
  #
  # If use_deprecated is True, Fuchsia's pinned Go (v1.8) is used and version
  # is ignored.
  def ensure_go(self, use_deprecated=False, version=None):
    """Ensures that go distribution is installed."""
    with self.m.step.nest('ensure_go'):
      with self.m.context(infra_steps=True):
        package = 'infra/go'
        version = version or 'version:1.9.4'
        if use_deprecated:
          package = 'fuchsia/go'
          version = 'release'

        go_package = ('%s/%s' %
            (package, self.m.cipd.platform_suffix()))
        self._go_dir = self.m.path['start_dir'].join('cipd', 'go')
        self.m.cipd.ensure(self._go_dir, {go_package: version})

        return self._go_dir

  @property
  def go_root(self):
    return self._go_dir

  @property
  def go_executable(self):
    return self.m.path.join(self._go_dir, 'bin', 'go')

  def inline(self, program, add_go_log=True, **kwargs):
    """Run an inline Go program as a step.
    Program is output to a temp file and run when this step executes.
    """
    program = textwrap.dedent(program)

    try:
      self('run', self.m.raw_io.input(program, '.go'), **kwargs)
    finally:
      result = self.m.step.active_result
      if result and add_go_log:
        result.presentation.logs['go.inline'] = program.splitlines()

    return result
