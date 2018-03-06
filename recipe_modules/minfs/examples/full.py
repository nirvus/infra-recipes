# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'minfs',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
    minfs_path = api.path['start_dir'].join('out', 'build-zircon', 'tools',
                                            'minfs')

    # Ensure no default path exists & that it can be set.
    assert not api.minfs.minfs_path
    api.minfs.minfs_path = minfs_path
    assert api.minfs.minfs_path == minfs_path

    # Create a 200mb minfs image with a specific name
    api.minfs.create(
        path=api.path.join(api.path['start_dir'], 'image.minfs'), size="200M")

    # Copy a file from that image
    api.minfs.cp('file-on-image.json', 'file-on-host.json', 'image.minfs')

    # Copy everything from the image
    api.minfs.copy_image('copy_image_step', 'image.minfs', 'output_path')


def GenTests(api):
    yield api.test('basic')
