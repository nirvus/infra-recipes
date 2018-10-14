# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'buildsetlookup',
    'recipe_engine/path',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  api.buildsetlookup.ensure_buildset_lookup()
  assert api.buildsetlookup.buildset_lookup_tool

  api.buildsetlookup(
      step_name='test',
      builder='fuchsia/ci/garnet-x64-qemu_kvm',
      buildset=
      'commit/gitiles/fuchsia.googlesource.com/topaz/+/e3127e0bd6d57da7a5959ee70eb0a396590e6d53',
  )


def GenTests(api):
  yield api.test('basic')
