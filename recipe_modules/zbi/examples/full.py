# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'zbi',
]


def RunSteps(api):
    zbi_path = api.path['start_dir'].join('out', 'build-zircon', 'tools', 'zbi')

    # Ensure no default path already exists and that it can be set.
    assert not api.zbi.zbi_path
    api.zbi.zbi_path = zbi_path
    assert api.zbi.zbi_path == zbi_path

    # Create a zbi image from a given image and manifest.
    api.zbi.copy_and_extend(
                step_name='copy and extend',
                input_image=api.path['start_dir'].join('input.zbi'),
                output_image=api.path['start_dir'].join('output.zbi'),
                manifest={
                  'path/to/dest/1' : api.path['start_dir'].join('src/1'),
                  'path/to/dest/2' : api.path['start_dir'].join('src/2')
                }
    )

def GenTests(api):
    manifest_data = api.step_data(
        'copy and extend',
        api.raw_io.output('output.zbi manifest')
    )

    yield api.test('copy and extend') + manifest_data
