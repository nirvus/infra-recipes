# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'infra/ninja',
    'recipe_engine/path',
]


def RunSteps(api):
  api.ninja.set_path(api.path['start_dir'].join('ninja'))
  api.ninja(
      build_dir=api.path['start_dir'].join('build'),
      targets=['//foo', '//bar'],
      job_count=42,
      build_file=api.path['start_dir'].join('build.ninja'),
      fail_threshold=2,
      verbose=True,
  )


def GenTests(api):
  yield api.test('basic')
