# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import os


class TarApi(recipe_api.RecipeApi):
  """Provides steps to tar and untar files."""

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

  def create(self, archive, compression=None):
    """Returns TarPackage object that can be used to compress a set of files."""
    assert compression is None or compression in ['gzip', 'bzip2', 'xz', 'lzma']
    return TarPackage(self, archive, compression)

  def extract(self, step_name, archive, dir=None, verbose=False):
    """Step to uncompress |tar_file| file."""
    assert self._bsdtar_path
    cmd = [
      self._bsdtar_path,
      '-xf',
      archive,
    ]
    if dir:
      cmd.extend(['-C', dir])
    if verbose:
      cmd.append('-v')
    return self.m.step(
        step_name,
        cmd
    )


class TarPackage(object):
  """Used to gather a list of files to tar."""

  def __init__(self, module, archive, compression):
    self._module = module
    self._archive = archive
    self._compression = compression
    self._entries = {}

  @property
  def archive(self):
    return self._archive

  def add(self, path, dir=None):
    """Stages single file to be added to the package.

    Args:
      path: absolute path to a file, should be in |root| subdirectory.
      archive_name: name of the file in the archive, if non-None
    """
    if not dir:
      dir = self._module.m.context.cwd
    assert dir.is_parent_of(path), path
    self._entries.setdefault(str(dir), []).append(str(path))

  def tar(self, step_name):
    """Step to tar all staged files."""
    assert self._module._bsdtar_path
    cmd = [
      self._module._bsdtar_path,
      '-cf',
      self._archive
    ]
    if self._compression:
      cmd.append({
        'gzip': '-z',
        'bzip2': '-j',
        'xz': '-J',
        'lzma': '--lzma',
      }[self._compression])
    for k in sorted(self._entries.iterkeys()):
      cmd.extend(['-C', k] + [os.path.relpath(p, k) for p in self._entries[k]])

    step_result = self._module.m.step(
        step_name,
        cmd
    )
    self._module.m.path.mock_add_paths(self._archive)
    return step_result
