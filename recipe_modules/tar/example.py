# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/shutil',
  'recipe_engine/step',
  'tar',
]


def RunSteps(api):
  # Ensure that tar binary is installed.
  api.tar.ensure_tar()

  # Prepare files.
  temp = api.path.mkdtemp('tar-example')
  api.step('touch a', ['touch', temp.join('a')])
  api.step('touch b', ['touch', temp.join('b')])
  api.shutil.makedirs('mkdirs', temp.join('sub', 'dir'))
  api.step('touch c', ['touch', temp.join('sub', 'dir', 'c')])

  # Build a tar file.
  package = api.tar.create(temp.join('more.tar.gz'), 'gzip')
  package.add(temp.join('a'), temp)
  with api.step.context({'cwd': temp}):
    package.add(temp.join('b'))
  package.add(temp.join('sub', 'dir', 'c'), temp.join('sub'))
  package.tar('taring more')

  # Coverage for 'output' property.
  api.step('report', ['echo', package.archive])

  # Untar the package.
  api.tar.extract('untaring', temp.join('output.tar'), temp.join('output'),
                  verbose=True)
  # List untarped content.
  with api.step.context({'cwd': temp.join('output')}):
    api.step('listing', ['find'])
  # Clean up.
  api.shutil.rmtree(temp)


def GenTests(api):
  for platform in ('linux', 'mac'):
    yield api.test(platform) + api.platform.name(platform)
