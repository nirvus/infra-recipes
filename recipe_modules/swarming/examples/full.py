# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'swarming',
  'recipe_engine/json',
  'recipe_engine/path',
]


def RunSteps(api):
  api.swarming.ensure_swarming()
  assert api.swarming.swarming_client

  api.swarming.swarming_server = 'chromium-swarm-dev.appspot.com'

  json = api.path['tmp_base'].join('task.json')

  # Trigger a new Swarming task.
  api.swarming.trigger('recipes-go',
      ['recipes', 'run', '"example"'],
      isolated='606d94add94223636ee516c6bc9918f937823ccc',
      dump_json=json,
      dimensions={'pool': 'Fuchsia', 'os': 'Debian'},
      expiration=3600,
      io_timeout=600,
      idempotent=True,
      outputs=['out/hello.txt'],
      cipd_packages=[('cipd_bin_packages', 'infra/git/${platform}', 'version:2.14.1.chromium10')],
  )

  # Wait for its results.
  try:
    results = api.swarming.collect('1m', requests_json=json)
    if not results[0].is_failure() and not results[0].is_infra_failure():
      # Get the path of an output like this!
      path = results[0]['out/hello.txt']
  except:
    pass

  # You can also wait on arbitrary tasks.
  api.swarming.collect(tasks=['398db31cc90be910', 'a9123129aaaaaa'], timeout=30)

  # You can also run an arbitrary command.
  api.swarming('version')


def GenTests(api):
  yield api.test('basic') + api.step_data('collect', api.swarming.collect_result(output='hello', outputs=['out/hello.txt']))
  yield api.test('task_failure') + api.step_data('collect', api.swarming.collect_result(task_failure=True))
  yield api.test('infra_failure') + api.step_data('collect', api.swarming.collect_result(infra_failure=True))
  yield api.test('infra_failure_no_out') + api.step_data('collect', api.json.output({}))
