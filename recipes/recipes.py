# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing Recipes."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/jiri',
  'recipe_engine/buildbucket',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/step',
]

PROPERTIES = {
  'project':
      Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
}


def RunSteps(api, project, manifest, remote):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest=manifest,
                      remote=remote,
                      project=project,
                      build_input=api.buildbucket.build.input)

  with api.context(cwd=api.path['start_dir'].join('infra', 'recipes')):
    api.python('test', api.context.cwd.join('recipes.py'),
               args=['test', 'run'])


def GenTests(api):
  yield (api.test('cq_try') +
    api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/infra/recipes'
    ) +
    api.properties.tryserver(
        manifest='infra',
        remote='https://fuchsia.googlesource.com/manifest',
    )
  )
