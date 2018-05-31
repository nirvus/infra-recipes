# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for checking license text in the source code.

Requires topaz source to be present in the manifest.
"""

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/fuchsia',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = {
    'patch_gerrit_url':
        Property(kind=str, help='Gerrit host', default=None),
    'patch_project':
        Property(kind=str, help='Gerrit project', default=None),
    'patch_ref':
        Property(kind=str, help='Gerrit patch ref', default=None),
    'patch_storage':
        Property(kind=str, help='Patch location', default=None),
    'patch_repository_url':
        Property(kind=str, help='URL to a Git repository', default=None),
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use. Should include //topaz'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
    'revision':
        Property(kind=str, help='Revision of manifest to import', default=None),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, patch_storage,
             patch_repository_url, project, remote, manifest, revision):
  checkout = api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      revision=revision,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
  )
  licenses_path = checkout.root_dir.join('topaz', 'tools', 'check-licenses.sh')
  with api.context(cwd=checkout.root_dir):
    api.step('licenses', [licenses_path])


def GenTests(api):
  yield api.test('default') + api.properties(
      manifest='fuchsia', remote='https://fuchsia.googlesource.com/manifest')
