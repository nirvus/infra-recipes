# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'git',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]


def RunSteps(api):
  url = 'https://fuchsia.googlesource.com/fuchsia.git'

  api.git.checkout(
      url,
      path=api.properties.get('path'),
      ref=api.properties.get('revision'),
      remote=api.properties.get('remote'),
      file=api.properties.get('checkout_file'))

  with api.step.context({'cwd': api.properties.get('path') or api.path['start_dir'].join('fuchsia')}):
    api.git.get_hash()
    api.git.get_timestamp()

    # You can invoke arbitrary command on api.git.
    api.git('status', config={'foo': 'bar'})


def GenTests(api):
  yield api.test('basic')
  yield api.test('basic_path') + api.properties(path=api.path['start_dir'].join('foo'))
  yield api.test('basic_ref') + api.properties(revision='refs/foo/bar')
  yield api.test('basic_branch') + api.properties(revision='refs/heads/testing')
  yield api.test('basic_hash') + api.properties(
      revision='abcdef0123456789abcdef0123456789abcdef01')
  yield api.test('basic_file') + api.properties(checkout_file='README.md')
