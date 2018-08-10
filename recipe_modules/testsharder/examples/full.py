# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'testsharder',
    'recipe_engine/path',
]

def RunSteps(api):
  # Ensure that the testsharder is installed.
  api.testsharder.ensure_testsharder()

  # Run the test sharder.
  shards = api.testsharder.execute(
      'shard test specs',
      target_arch='x64',
      platforms_file=api.path['start_dir'].join('platforms.json'),
      fuchsia_build_dir=api.path['start_dir'].join('out'),
      output_file=api.path['start_dir'].join('leak_output_here'),
  )

  # You can add a shard prefix also.
  shards = api.testsharder.execute(
      'shard test specs with shard prefix',
      target_arch='x64',
      platforms_file=api.path['start_dir'].join('platforms.json'),
      fuchsia_build_dir=api.path['start_dir'].join('out'),
      output_file=api.path['start_dir'].join('leak_output_here'),
      shard_prefix='garnet',
  )


def GenTests(api):
  yield api.test('basic')
