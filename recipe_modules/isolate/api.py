# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


# TODO(mknyszek): Use golang isolated client instead.
class IsolateApi(recipe_api.RecipeApi):
  """APIs for interacting with isolates."""

  def __init__(self, isolate_server, *args, **kwargs):
    super(IsolateApi, self).__init__(*args, **kwargs)
    self._isolate_server = isolate_server
    self._isolate_client = None

  def __call__(self, *args, **kwargs):
    """Return an isolate command step."""
    assert self._isolate_client
    name = kwargs.pop('name', 'isolate ' + args[0])
    return self.m.step(name, [self._isolate_client] + list(args), **kwargs)

  def ensure_isolate(self, version=None):
    """Ensures that isolate client is installed."""
    with self.m.step.nest('ensure_isolate'):
      with self.m.context(infra_steps=True):
        isolate_package = ('infra/tools/luci/isolate/%s' %
            self.m.cipd.platform_suffix())
        luci_dir = self.m.path['start_dir'].join('cipd', 'luci', 'isolate')

        self.m.cipd.ensure(luci_dir,
                           {isolate_package: version or 'release'})
        self._isolate_client = luci_dir.join('isolate')

        return self._isolate_client

  @property
  def isolate_client(self):
    return self._isolate_client

  @property
  def isolate_server(self):
    """URL of Isolate server to use, default is a production one."""
    return self._isolate_server

  @isolate_server.setter
  def isolate_server(self, value):
    """Changes URL of Isolate server to use."""
    self._isolate_server = value

  def archive(self, isolate, isolated):
    """All the files in the .isolate file are put in the isolate server cache.

    Args:
      isolate: .isolate file to load the dependency data from.
      isolated: .isolated file to generate or read.
    """
    assert self._isolate_client
    cmd = [
      self._isolate_client,
      'archive',
      '-isolate-server', self.isolate_server,
      '-isolate', isolate,
      '-isolated', isolated,
      '-namespace', 'default-gzip',
      '-dump-json', self.m.json.output(),
    ]
    return self.m.step(
        'archive',
        cmd,
        step_test_data=lambda: self.test_api.archive(isolated)
    ).json.output
