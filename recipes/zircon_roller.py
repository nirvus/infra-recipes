# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for rolling Zircon into other projects."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/git',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
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
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'revision': Property(kind=str, help='Revision'),
}


COMMIT_MESSAGE = """This is an automated change created by the Zircon roller.

This change rolls Zircon from upstream project into downstream project.
"""


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote, revision):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, patch_ref, patch_gerrit_url, project)

    project_dir = api.path['start_dir'].join(*project.split('/'))
    with api.context(cwd=project_dir):
      api.jiri.edit_manifest(manifest, imports=[('zircon', revision)])
      api.git.commit(COMMIT_MESSAGE, api.path.join(*manifest.split('/')))
      api.git.push('HEAD:refs/for/master%l=Code-Review+2,l=Commit-Queue+2')


def GenTests(api):
  yield (api.test('basic') +
         api.properties(project='garnet',
                        manifest='manifest/garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07'))
