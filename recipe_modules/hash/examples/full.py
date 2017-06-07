# copyright 2017 the fuchsia authors. all rights reserved.
# use of this source code is governed by a bsd-style license that can be
# found in the license file.

DEPS = [
  'hash',
  'recipe_engine/path',
]


def RunSteps(api):
  for h in ['md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512']:
    getattr(api.hash, h)(h, api.path['start_dir'].join('file'))


def GenTests(api):
  yield api.test('basic')
