# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'infra/gn',
    'infra/goma',
    'recipe_engine/path',
]


def RunSteps(api):
  api.gn.set_path(api.path['start_dir'].join('gn'))
  api.gn('gen', '//a', '//b', '//c')


def GenTests(api):
  yield api.test('basic')
