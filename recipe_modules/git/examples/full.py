# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'git',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/time',
]


def RunSteps(api):
  url = 'https://fuchsia.googlesource.com/fuchsia.git'

  api.git.checkout(
      url,
      path=api.properties.get('path'),
      ref=api.properties.get('revision'),
      recursive=True,
      submodules=True,
      submodule_force=True,
      remote=api.properties.get('remote'),
      file=api.properties.get('checkout_file'))

  root_dir = api.properties.get('path') or api.path['start_dir'].join('fuchsia')

  with api.context(cwd=root_dir):
    api.git.get_hash()
    api.git.get_timestamp()

    # You can invoke arbitrary command on api.git.
    api.git('status', config={'foo': 'bar'})

    # You can use api.git.rebase to rebase the current branch onto another one
    api.git.rebase(branch='master', remote='origin')

    # Add a new file
    api.file.write_text(
        'drop file', root_dir.join('time.txt'), str(api.time.time()))
    api.git('add', root_dir.join('time.txt'))

    # Commit the change
    api.git.commit('example change 1')

    # Commit the change with the file named explicitly
    api.git.commit('example change 2', files=[root_dir.join('time.txt')])

    # Commit the change with all tracked files
    api.git.commit('example change 3', all_tracked=True)

    # Push it for review
    api.git.push('HEAD:refs/for/master')


def GenTests(api):
  yield api.test('basic')
  yield api.test('basic_path') + api.properties(path=api.path['start_dir'].join('foo'))
  yield api.test('basic_ref') + api.properties(revision='refs/foo/bar')
  yield api.test('basic_branch') + api.properties(revision='refs/heads/testing')
  yield api.test('basic_hash') + api.properties(
      revision='abcdef0123456789abcdef0123456789abcdef01')
  yield api.test('basic_file') + api.properties(checkout_file='README.md')
