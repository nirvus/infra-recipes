# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building and testing Cobalt."""

from recipe_engine.config import ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/jiri',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
}

RETURN_SCHEMA = ReturnSchema(
  got_revision=Single(str)
)


def RunSteps(api, patch_gerrit_url, patch_ref, manifest, remote):
  api.jiri.ensure_jiri()

  with api.step.context({'infra_step': True}):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote)
    api.jiri.clean()
    api.jiri.update()
    revision = api.jiri.project('cobalt').json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url, rebase=True)

  # Start the cobalt build process.
  with api.step.context({'cwd': api.path['start_dir'].join('cobalt')}):
    for step in ["setup", "build", "test"]:
      api.step(step, ["./cobaltb.py", step])

  return RETURN_SCHEMA.new(got_revision=revision)


def GenTests(api):
  yield api.test('ci') + api.properties(
      manifest='cobalt',
      remote='https://fuchsia.googlesource.com/manifest'
  )
  yield api.test('cq_try') + api.properties.tryserver(
      gerrit_project='cobalt',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='cobalt',
      remote='https://fuchsia.googlesource.com/manifest',
  )
