# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building and testing Cobalt."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref,
             project, manifest, remote):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    revision = api.jiri.project(['cobalt']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  # Start the cobalt build process.
  with api.context(cwd=api.path['start_dir'].join('cobalt')):
    api.step('setup', ['./cobaltb.py', 'setup'])
    api.step('build', ['./cobaltb.py', 'build'])
    api.step('lint', ['./cobaltb.py', 'lint'])
    api.step('test', ['./cobaltb.py', 'test'])


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
