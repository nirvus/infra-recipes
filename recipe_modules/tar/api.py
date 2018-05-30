# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import os


class TarApi(recipe_api.RecipeApi):
  """Provides steps to tar and untar files."""

  COMPRESSION_OPTS = ['gzip', 'bzip2', 'xz', 'lzma']

  def __init__(self, *args, **kwargs):
    super(TarApi, self).__init__(*args, **kwargs)
    self._bsdtar_path = None

  def ensure_tar(self, version=None):
    """Ensures that bsdtar is installed."""
    with self.m.step.nest('ensure bsdtar'):
      with self.m.context(infra_steps=True):
        bsdtar_package = ('fuchsia/tools/bsdtar/%s' %
            self.m.cipd.platform_suffix())
        bsdtar_dir = self.m.path['start_dir'].join('cipd')

        self.m.cipd.ensure(
            bsdtar_dir, {bsdtar_package: version or 'latest'})
        self._bsdtar_path = bsdtar_dir.join('bsdtar')

        return self._bsdtar_path

  def create(self, path, compression=None):
    """Returns TarArchive object that can be used to compress a set of files.

    Args:
      path: path of the archive file to be created.
      compression: str, one of COMPRESSION_OPTS or None to disable compression.
    """
    assert not compression or compression in TarApi.COMPRESSION_OPTS, (
        'compression must be one of %s', TarApi.COMPRESSION_OPTS)
    return TarArchive(self, path, compression)

  def extract(self, step_name, path, directory=None, strip_components=None):
    """Uncompress |archive| file.

    Args:
      step_name: name of the step.
      path: absolute path to archive file.
      directory: directory to extract the archive in.
      strip_components: strip number of leading components from file names.
    """
    assert self._bsdtar_path
    # We use long-form options whenever possible, but for options with
    # arguments, we have to use the short form. The recipe engine tests require
    # objects which might be placeholders (in this case |path|) to be their own
    # argument, and the version of tar we're using doesn't support
    # '--long-opt arg'. It only supports '--long-opt=arg' or short-form like
    # '-s arg'.
    cmd = [
      self._bsdtar_path,
      '--extract',
      '--verbose',
      '-f',
      path,
    ]
    if directory:
      cmd.extend(['-C', directory])
    if strip_components:
      cmd.extend(['--strip-components', str(int(strip_components))])
    return self.m.step(step_name, cmd)


class TarArchive(object):
  """Used to gather a list of files to tar."""

  def __init__(self, module, path, compression):
    self._module = module
    self._path = path
    self._compression = compression
    self._entries = {}

  @property
  def path(self):
    return self._path

  def add(self, path, directory=None):
    """Stages single file to be added to the package.

    Args:
      path: absolute path to a file, should be a child of |directory|.
      directory: ancestor directory of |path|. The name of the file
          inside the archive will not include |directory|. Defaults to $CWD.
    """
    if not directory:
      directory = self._module.m.context.cwd
    assert directory.is_parent_of(path), (
        'directory must be a parent of path. directory: %s.%s, path: %s.%s'
        % (directory.base, directory.pieces, path.base, path.pieces))
    self._entries.setdefault(str(directory), []).append(str(path))

  def tar(self, step_name):
    """Step to tar all staged files."""
    assert self._module._bsdtar_path
    cmd = [
      self._module._bsdtar_path,
      '--create',
      '-f',
      self._path
    ]
    if self._compression:
      cmd.append('--%s' % self._compression)
    for directory in sorted(self._entries):
      cmd.extend(['-C', directory] + [
          os.path.relpath(p, directory) for p in self._entries[directory]])

    step_result = self._module.m.step(step_name, cmd)
    self._module.m.path.mock_add_paths(self._path)
    return step_result
