# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building and running pre-submit checks for the modules repo."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/goma',
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
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'project_path': Property(kind=str, help='Project path', default=None),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, project_path):
  api.goma.ensure_goma()
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, patch_ref, patch_gerrit_url)

  # The make script defaults to a debug build unless specified otherwise. It
  # also always hardcodes x86-64 as the target architecture. Since this is
  # only exercising Dart code we don't parameterize the recipe for any other
  # architecture.
  ctx = {
    'cwd': api.path['start_dir'].join(project_path),
    'env': {
      'fuchsia_root': api.path['start_dir'],
      'GOMA': 1, 'MINIMAL': 1, 'NO_ENSURE_GOMA': 1,
      'GOMA_DIR': api.goma.goma_dir,
      'PUB_CACHE': api.path['cache'].join('pub')
    }
  }

  with api.goma.build_with_goma():
    with api.context(**ctx):
      api.step('build and run presubmit tests', ['make', 'presubmit-cq'])


def GenTests(api):
  yield api.test('basic') + api.properties(
      patch_project='modules/common',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
  )
  yield api.test('cq') + api.properties.tryserver(
      gerrit_project='modules/common',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      project_path='apps/modules/common',
  )
