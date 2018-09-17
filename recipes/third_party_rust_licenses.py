# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for checking licenses in the repo hosting third-party Rust crates."""

from recipe_engine.config import ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]


def RunSteps(api):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest('third_party_rust_crates',
                             'https://fuchsia.googlesource.com/manifest')
    api.jiri.update()

  cmd = [
    api.path['start_dir'].join('scripts', 'rust', 'check_rust_licenses.py'),
    '--verify',
    '--directory',
    api.path['start_dir'].join(
        'third_party', 'rust-crates', 'rustc_deps', 'vendor'),
  ]
  api.step('verify licenses', cmd)


def GenTests(api):
  yield api.test('basic')
