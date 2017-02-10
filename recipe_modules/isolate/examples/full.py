# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'isolate',
  'recipe_engine/json',
  'recipe_engine/path',
]


def RunSteps(api):
  api.isolate.ensure_isolate()
  assert api.isolate.isolate_client

  api.isolate.isolate_server = 'isolateserver.appspot.com'

  # Create an isolated from isolate.
  test_isolated = api.path['tmp_base'].join('test.isolated')
  api.isolate.archive(api.json.input(
    {
      'variables': {
        'files': [
          'test',
        ]
      }
    }), test_isolated)

  # You can also run an arbitrary command.
  api.isolate('version')


def GenTests(api):
  yield api.test('basic')
