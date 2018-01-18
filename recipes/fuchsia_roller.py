# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for rolling Fuchsia layers into upper layers."""

import time

from recipe_engine.recipe_api import Property


DEPS = [
  'infra/gerrit',
  'infra/git',
  'infra/gitiles',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/json',
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
  'dry_run': Property(kind=bool, help='Whether to only execute a CQ dry run', default=False),
  'poll_timeout': Property(kind=float,
                           default=50*60,
                           help='The total amount of seconds to spend polling before timing out'),
  'poll_interval': Property(kind=float,
                            default=5*60,
                            help='The interval at which to poll in seconds'),
}


FUCHSIA_URL = 'https://fuchsia.googlesource.com/'

COMMIT_MESSAGE = """Roll {project} {old}..{new} ({count} commits)

{commits}
"""


def RunSteps(api, category, project, manifest, remote, import_in, import_from, revision,
             dry_run, poll_timeout, poll_interval):
  api.jiri.ensure_jiri()
  api.gerrit.ensure_gerrit()
  api.gerrit.host = 'https://fuchsia-review.googlesource.com'
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
                commit=commit['id'][:7],
                subject=commit['message'].splitlines()[0],
            ) for commit in log
          ]),
      )

      # Use the old method if it's not a dry run.
      if not dry_run:
        api.git.commit(message, api.path.join(*import_in.split('/')))
        api.git.push('HEAD:refs/for/master%l=Code-Review+2,l=Commit-Queue+2')
        return

      # Create a new change for the roll.
      change = api.gerrit.create_change('create new change', project, message, 'master')
      change_id = change['id']

      # Update message with a Change-Id line and push the roll.
      message += "\nChange-Id: %s\n" % change['change_id']
      api.git.commit(message, api.path.join(*import_in.split('/')))
      api.git.push('HEAD:refs/for/master')

      # Activate CQ.
      labels = {'Commit-Queue': 1 if dry_run else 2}
      if not dry_run: # pragma: no cover
        labels['Code-Review'] = 2
      api.gerrit.set_review(
          'submit to commit queue',
          change_id,
          labels=labels,
      )

  # Poll gerrit to see if CQ was successful.
  # TODO(mknyszek): Figure out a cleaner solution than polling.
  for i in range(int(poll_timeout/poll_interval)):
    # Sleep for poll_interval milliseconds.
    # TODO(mknyszek): Mock sleep so we're not actually sleeping during tests.
    time.sleep(poll_interval)

    # Check the status of the CL.
    with api.context(infra_steps=True):
      change = api.gerrit.change_details('check if done (%d)' % i, change_id)

    # If it merged, then great! We're done.
    # However, it the CQ label is un-set, then that means the roll failed.
    if change['status'] == 'MERGED':
      return
    elif 'approved' not in change['labels']['Commit-Queue']:
      api.gerrit.abandon('abandon roll', change_id)
      raise api.step.StepFailure('Failed to roll changes: CQ failed.')
  raise api.step.InfraFailure('Failed to roll changes: roller timed out.')


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

  new_change_data = api.step_data(
    'create new change',
    api.json.output({
      'id': 'abc123',
      'change_id': 'abc123',
    }),
  )
  # This test case is technically never possible, but exists to ease the
  # transition to the new polling-based roller.
  yield (api.test('zircon_dry_run') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        dry_run=True,
                        poll_interval=0.001,
                        poll_timeout=0.1) +
         api.gitiles.log('log', 'A') + new_change_data +
         api.step_data('check if done (0)', api.json.output({'status': 'MERGED'})))
  yield (api.test('zircon_cq_failure') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        dry_run=True,
                        poll_interval=0.001,
                        poll_timeout=0.1) +
         api.gitiles.log('log', 'A') + new_change_data +
         api.step_data('check if done (0)', api.json.output({
             'status': 'NEW',
             'labels': {
                 'Commit-Queue': {
                     'disliked': {}
                 }
             }
         })))
  yield (api.test('zircon_timeout') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        dry_run=True,
                        poll_interval=0.001,
                        poll_timeout=0.001) +
         api.gitiles.log('log', 'A') + new_change_data +
         api.step_data('check if done (0)', api.json.output({
             'status': 'NEW',
             'labels': {
                 'Commit-Queue': {
                     'approved': {}
                 }
             }
         })))
