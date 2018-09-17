# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for checking license text in the source code.

Requires topaz source to be present in the manifest.
"""

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/fuchsia',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = {
    'project':
      Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use. Should include //topaz'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
}


def RunSteps(api, project, remote, manifest):
  checkout = api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      build_input=api.buildbucket.build.input,
  )
  licenses_path = checkout.root_dir.join('topaz', 'tools', 'check-licenses.sh')
  with api.context(cwd=checkout.root_dir):
    api.step('licenses', [licenses_path])


def GenTests(api):
  yield (api.test('default_ci') +
    api.buildbucket.ci_build(
      git_repo='https://fuchsia.googlesource.com/topaz'
    ) +
    api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
    )
  )

  yield (api.test('default_cq') +
    api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/topaz'
    ) +
    api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
    )
  )
