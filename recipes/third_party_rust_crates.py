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

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
}

RETURN_SCHEMA = ReturnSchema(
  got_revision=Single(str)
)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest('runtimes/rust',
                             'https://fuchsia.googlesource.com/manifest')
    api.jiri.import_manifest('build',
                             'https://fuchsia.googlesource.com/manifest')
    api.jiri.update()
    revision = api.jiri.project('rust-crates').json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

    step_result = api.jiri.snapshot(api.raw_io.output())
    snapshot = step_result.raw_io.output
    step_result.presentation.logs['jiri.snapshot'] = snapshot.splitlines()

    if patch_ref is not None:
      api.jiri.patch(patch_ref, host=patch_gerrit_url)

  cmd = [
    api.path['start_dir'].join('scripts', 'check_rust_licenses.py'),
    '--verify',
    '--directory',
    api.path['start_dir'].join('third_party', 'rust-crates', 'vendor'),
  ]
  api.step('verify licenses', cmd)

  return RETURN_SCHEMA.new(got_revision=revision)


def GenTests(api):
  yield api.test('basic')
  yield api.test('patch') + api.properties(
      patch_ref='abcd1234',
      patch_gerrit_url='https://abcd.com/1234',
  )
