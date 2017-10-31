# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for rolling Fuchsia layers into upper layers."""

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
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'import_in': Property(kind=str, help='Name of the manifest to import in'),
  'import_from': Property(kind=str, help='Name of the manifest to import from'),
  'revision': Property(kind=str, help='Revision'),
}


COMMIT_MESSAGE = """Roll {0} to {1}

This is an automated change created by the {0} roller.
"""


def RunSteps(api, category, project, manifest, remote, import_in, import_from, revision):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, project)
    api.jiri.update(run_hooks=False)

    project_dir = api.path['start_dir'].join(*project.split('/'))
    with api.context(cwd=project_dir):
      api.jiri.edit_manifest(import_in, imports=[(import_from, revision)])
      api.git.commit(COMMIT_MESSAGE.format(import_from, revision[:7]),
                     api.path.join(*import_in.split('/')))
      api.git.push('HEAD:refs/for/master%l=Code-Review+2,l=Commit-Queue+2')


def GenTests(api):
  yield (api.test('zircon') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        remote='https://fuchsia.googlesource.com/garnet',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07'))
  yield (api.test('garnet') +
         api.properties(project='peridot',
                        manifest='manifest/minimal',
                        import_in='manifest/peridot',
                        import_from='garnet',
                        remote='https://fuchsia.googlesource.com/peridot',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07'))
  yield (api.test('peridot') +
         api.properties(project='manifest',
                        manifest='minimal',
                        import_in='topaz',
                        import_from='peridot',
                        remote='https://fuchsia.googlesource.com/manifest',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07'))
