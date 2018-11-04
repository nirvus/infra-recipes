# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from recipe_engine import recipe_api


class QemuApi(recipe_api.RecipeApi):
  """QemuApi provides support for QEMU."""

  def __init__(self, *args, **kwargs):
    super(QemuApi, self).__init__(*args, **kwargs)
    self._qemu_dir = None

  def ensure_qemu(self, version=None):
    with self.m.step.nest('ensure_qemu'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'qemu')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('fuchsia/qemu/${platform}', version or 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._qemu_dir = cipd_dir.join('qemu')
        return self._qemu_dir

  @property
  def qemu_img(self):
    return self.m.path.join(self._qemu_dir, 'bin', 'qemu-img')

  def create_image(self, image, backing_file, fmt='qcow2'):
    """Creates a QEMU image from a backing file.

    Args:
      image (Path): Path to the image to be created.
      backing_file (Path): The backing file to use for the image.
      fmt (str): The format of the image.
    """
    result = self.m.step(
        'qemu-img create %s' % self.m.path.basename(image),
        [
          self.qemu_img,
          'create',
          '-f', fmt,
          '-b', backing_file,
          image,
        ],
    )
    result.step_text = 'from %s (fmt: %s)' % (
        self.m.path.basename(backing_file),
        fmt,
    )
    return result
