# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'gitiles',
    'recipe_engine/properties',
]


def RunSteps(api):
  api.gitiles.ensure_gitiles()
  url = 'https://fuchsia.googlesource.com/fuchsia'
  for ref, commit in api.gitiles.refs(url).iteritems():
    api.gitiles.log(url, ref, limit=10)

  data = api.gitiles.fetch(url, 'OWNERS', test_data='foobar')
  assert data == 'foobar'


def GenTests(api):
  yield (
      api.test('basic')
      + api.gitiles.refs('refs',
          'refs/heads/A',
          'refs/heads/B',
      )
      + api.gitiles.log(
          'gitiles log: refs/heads/A',
          'A',
      )
      + api.gitiles.log(
          'gitiles log: refs/heads/B',
          'B',
      )
      + api.gitiles.fetch(
          'fetch master:OWNERS',
          'foobar'
      )
  )
