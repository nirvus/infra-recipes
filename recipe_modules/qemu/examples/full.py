# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
  'qemu',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/path',
]

PROPERTIES = {}


def RunSteps(api):
  # First, you need a QEMU.
  api.qemu.ensure_qemu()

  # Create an image from an FVM block device.
  backing_file = api.path['start_dir'].join('fvm.blk')
  disk_img = api.path['start_dir'].join('disk.img')
  api.qemu.create_image(disk_img, backing_file)


def GenTests(api):
  yield (
      api.test('basic') +
      api.properties.generic() +
      api.platform('linux', 64)
  )
