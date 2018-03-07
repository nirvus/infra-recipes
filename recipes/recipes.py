# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing Recipes."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/step',
]

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'revision': Property(kind=str, help='Revision of manifest to import', default=None),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, project,
             manifest, remote, revision):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest=manifest,
                      remote=remote,
                      project=project,
                      revision=revision,
                      patch_ref=patch_ref,
                      patch_gerrit_url=patch_gerrit_url,
                      patch_project=patch_project)
    if not revision:
      revision = api.jiri.project(['infra/recipes']).json.output[0]['revision']
      api.step.active_result.presentation.properties['got_revision'] = revision

  with api.context(cwd=api.path['start_dir'].join('infra', 'recipes')):
    api.python('test', api.context.cwd.join('recipes.py'),
               args=['test', 'run'])


def GenTests(api):
  yield api.test('cq_try') + api.properties.tryserver(
      gerrit_project='infra/recipes',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='infra',
      remote='https://fuchsia.googlesource.com/manifest',
  )
