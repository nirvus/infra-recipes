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

  # One may access a number of different aspects of the shard easily as it is a
  # Python object.
  for shard in shards:
    shard.name
    shard.device_type
    for test in shard.tests:
      test.name
      test.location

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
  step_data = lambda name: api.testsharder.execute(
       step_name=name,
       shards=[
          api.testsharder.shard(
        name='0000',
        device_type='QEMU',
        tests=[api.testsharder.test(
            name='test1', location='/path/to/test1')],
      ),
      api.testsharder.shard(
        name='0001',
        device_type='NUC',
        tests=[api.testsharder.test(
            name='test1', location='/path/to/test1')],
      ),
  ])
  yield (api.test('basic') +
         step_data('shard test specs') +
         step_data('shard test specs with shard prefix'))
