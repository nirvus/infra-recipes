# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for rolling Fuchsia layers into upper layers."""

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/git',
  'infra/gitiles',
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


FUCHSIA_URL = 'https://fuchsia.googlesource.com/'

COMMIT_MESSAGE = """Roll {project} {old}..{new} ({count} commits)

{commits}
"""


def RunSteps(api, category, project, manifest, remote, import_in, import_from, revision):
  api.jiri.ensure_jiri()
  api.gitiles.ensure_gitiles()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, project)
    api.jiri.update(run_hooks=False)

    project_dir = api.path['start_dir'].join(*project.split('/'))
    with api.context(cwd=project_dir):
      changes = api.jiri.edit_manifest(import_in, imports=[(import_from, revision)])
      old_rev = changes['imports'][0]['old_revision']
      new_rev = changes['imports'][0]['new_revision']
      url = FUCHSIA_URL + import_from
      log = api.gitiles.log(url, '%s..%s' % (old_rev, new_rev), step_name='log')
      message = COMMIT_MESSAGE.format(
          project=import_from,
          old=old_rev[:7],
          new=new_rev[:7],
          count=len(log),
          commits='\n'.join([
            '{commit} {subject}'.format(
                commit=commit['commit'][:7],
                subject=commit['message'].splitlines()[0],
            ) for commit in log
          ]),
      )
      api.git.commit(message, api.path.join(*import_in.split('/')))
      api.git.push('HEAD:refs/for/master%l=Code-Review+2,l=Commit-Queue+2')


def GenTests(api):
  yield (api.test('zircon') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07') +
         api.gitiles.log('log', 'A'))
  yield (api.test('garnet') +
         api.properties(project='peridot',
                        manifest='manifest/minimal',
                        import_in='manifest/peridot',
                        import_from='garnet',
                        remote='https://fuchsia.googlesource.com/peridot',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07') +
         api.gitiles.log('log', 'A'))
  yield (api.test('peridot') +
         api.properties(project='topaz',
                        manifest='manifest/minimal',
                        import_in='manifest/topaz',
                        import_from='peridot',
                        remote='https://fuchsia.googlesource.com/topaz',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07') +
         api.gitiles.log('log', 'A'))
