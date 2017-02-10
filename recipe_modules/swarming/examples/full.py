# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'swarming',
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
      cipd_packages=[('cipd_bin_packages', 'infra/git/${platform}', 'version:2.14.1.chromium10')],
  )

  # Wait for its results.
  api.swarming.collect('1m', requests_json=json)

  # You can also wait on arbitrary task.
  api.swarming.collect(tasks=['398db31cc90be910'], timeout=30)

  # You can also run an arbitrary command.
  api.swarming('version')


def GenTests(api):
  yield api.test('basic')
