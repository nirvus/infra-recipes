# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import os


class IsolatedApi(recipe_api.RecipeApi):
  """APIs for interacting with isolates."""

  def __init__(self, isolate_server, *args, **kwargs):
    super(IsolatedApi, self).__init__(*args, **kwargs)
    self._isolate_server = isolate_server
    self._isolated_client = None

  def __call__(self, *args, **kwargs):
    """Return an isolate command step."""
    assert self._isolated_client
    name = kwargs.pop('name', 'isolate ' + args[0])
    return self.m.step(name, [self._isolated_client] + list(args), **kwargs)

  def ensure_isolated(self, version=None):
    """Ensures that isolate client is installed."""
    if self._isolated_client:
      return self._isolated_client

    with self.m.step.nest('ensure_isolated'):
      with self.m.context(infra_steps=True):
        isolate_package = (
            'infra/tools/luci/isolated/%s' % self.m.cipd.platform_suffix())
        luci_dir = self.m.path['start_dir'].join('cipd', 'luci', 'isolate')

        self.m.cipd.ensure(luci_dir, {isolate_package: version or 'release'})
        self._isolated_client = luci_dir.join('isolated')

        return self._isolated_client

  @property
  def isolated_client(self):
    return self._isolated_client

  @property
  def isolate_server(self):
    """URL of Isolate server to use, default is a production one."""
    return self._isolate_server

  @isolate_server.setter
  def isolate_server(self, value):
    """Changes URL of Isolate server to use."""
    self._isolate_server = value

  def isolated(self):
    """Returns an Isolated object that can be used to archive a set of files
    and directories."""
    return Isolated(self)


class Isolated(object):
  """Used to gather a list of files and directories to an isolated."""

  def __init__(self, module):
    self._module = module
    self._files = {}
    self._dirs = {}

  def add_file(self, path, wd=None):
    """Stages a single file to be added to the isolated.

    The isolated client implements a tar-like scatter-gather mechanism for
    archiving files. |path| refers to an absolute path to the file, while
    |cwd| is some subset of |path| which will become the path used by the
    isolated client.

    For example, /usr/local/data/foo can be added to the isolated as
    data/foo by specifying wd=/usr/local.

    Args:
      path: absolute path to a file.
      cwd: absolute path to the working directory for the file.
    """
    assert path
    wd = wd or self._module.m.context.cwd
    assert wd.is_parent_of(path)
    self._files.setdefault(str(wd), []).append(str(path))

  def add_dir(self, path, wd=None):
    """Stages a single directory to be added to the isolated.

    The isolated client implements a tar-like scatter-gather mechanism for
    archiving directories. |path| refers to an absolute path to the directory,
    while |cwd| is some subset of |path| which will become the path used by the
    isolated client.

    For example, /usr/local/data/foo can be added to the isolated as
    data/foo by specifying wd=/usr/local.

    Args:
      path: absolute path to a directory.
      cwd: absolute path to the working directory for the directory.
    """
    assert path
    wd = wd or self._module.m.context.cwd
    assert wd.is_parent_of(path)
    self._dirs.setdefault(str(wd), []).append(str(path))

  def archive(self, step_name):
    """Step to archive all staged files and directories."""
    assert self._module._isolated_client
    cmd = [
        self._module._isolated_client,
        'archive',
        '-isolate-server', self._module.isolate_server,
        '-namespace', 'default-gzip',
        '-dump-hash', self._module.m.raw_io.output_text(),
    ]
    for wd, files in self._files.iteritems():
      for f in files:
        cmd.extend(['-files', wd + ':' + os.path.relpath(f, wd)])
    for wd, dirs in self._dirs.iteritems():
      for d in dirs:
        cmd.extend(['-dirs', wd + ':' + os.path.relpath(d, wd)])
    return self._module.m.step(
        'archive',
        cmd,
        step_test_data=lambda: self._module.test_api.archive(),
    ).raw_io.output_text
