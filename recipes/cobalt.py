# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building and testing Cobalt."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/jiri',
  'recipe_engine/buildbucket',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/step',
]

PROPERTIES = {
  'project':
      Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
}


def RunSteps(api, manifest, remote):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest=manifest,
                      remote=remote,
                      build_input=api.buildbucket.build.input)

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
  yield (api.test('cq_try') +
    api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/cobalt'
    ) +
    api.properties.tryserver(
      manifest='cobalt',
      remote='https://fuchsia.googlesource.com/manifest',
    )
  )
