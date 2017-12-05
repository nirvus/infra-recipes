# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'isolated',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  api.isolated.ensure_isolated()
  assert api.isolated.isolated_client

  # Prepare files.
  temp = api.path.mkdtemp('isolated-example')
  api.step('touch a', ['touch', temp.join('a')])
  api.step('touch b', ['touch', temp.join('b')])
  api.file.ensure_directory('mkdirs', temp.join('sub', 'dir'))
  api.step('touch c', ['touch', temp.join('sub', 'dir', 'c')])

  api.isolated.isolate_server = 'isolateserver.appspot.com'

  # Create an isolated.
  isolated = api.isolated.isolated()
  isolated.add_file(temp.join('a'), temp)
  with api.context(cwd=temp):
    isolated.add_file(temp.join('b'))
  isolated.add_dir(temp.join('sub', 'dir'), temp)
  isolated.archive('archiving...')

  # You can also run an arbitrary command.
  api.isolated('version')


def GenTests(api):
  yield api.test('basic')
