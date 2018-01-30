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
  'recipe_engine/url',
]


PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'import_in': Property(kind=str, help='Name of the manifest to import in'),
  'import_from': Property(kind=str, help='Name of the manifest to import from'),
  'revision': Property(kind=str, help='Revision'),
  'dry_run': Property(kind=bool,
                      default=False,
                      help='Whether to dry-run the auto-roller (CQ+1 and abandon the change)'),
  'poll_timeout_secs': Property(kind=float,
                                default=50*60,
                                help='The total amount of seconds to spend polling before timing out'),
  'poll_interval_secs': Property(kind=float,
                                 default=5*60,
                                 help='The interval at which to poll in seconds'),
}


FUCHSIA_URL = 'https://fuchsia.googlesource.com/'

COMMIT_MESSAGE = """[manifest] Roll {project} {old}..{new} ({count} commits)

{commits}
"""


# This recipe has two 'modes' of operation: production and dry-run. Which mode
# of execution should be used is dictated by the 'dry_run' property. The
# differences between the two are as follows:
#
# Production Mode:
# * Create a patch locally
# * Push to Gerrit with Code-Review+2 and Commit-Queue+2.
# TODO(mknyszek): Wait for CQ to land the change in production.
#
# Dry-run Mode:
# * Create a patch locally
# * Push to Gerrit with Commit-Queue+1.
# * Wait for CQ to finish tryjobs.
# * Abandon the change to clean up.
#
# The purpose of dry-run mode is to test the auto-roller end-to-end. This is
# useful because now we can have an auto-roller in staging, and we can block
# updates behind 'dry_run' as a sort of feature gate.
def RunSteps(api, category, project, manifest, remote, import_in, import_from, revision,
             dry_run, poll_timeout_secs, poll_interval_secs):
  api.jiri.ensure_jiri()
  api.gerrit.ensure_gerrit()
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

      # Create a new change for the roll.
      change = api.gerrit.create_change('create new change', project, message, 'master')

      # NOTE: The project in a change_id may contain characters which are URL
      # encoded by gerrit (for example, '/'). This gets re-encoded by the
      # gerrit client underlying the gerrit recipe module for security, leading
      # to some strange results. By decoding first using api.url.unquote, we prevent
      # this from happening.

      # Represents the unique change ID for this change, usually of the form
      # <project>~<branch>~<change id> and is necessary for any API calls.
      full_change_id = api.url.unquote(change['id'])

      # Represents the change ID used in commit messages, which may not be
      # unique across projects and branches, but is useful for anything
      # UI-related.
      change_id = api.url.unquote(change['change_id'])

      # Surface a link to the change by querying gerrit for the change ID. If
      # it's the only commit with that change ID (highly likely) then it will
      # open it automatically. Unfortunately the unique change ID doesn't
      # exhibit this same behavior, so we avoid using it.
      api.step.active_result.presentation.links['gerrit link'] = api.url.join(
          api.gerrit.host, 'q', change_id)

      # Update message with a Change-Id line and push the roll.
      message += "\nChange-Id: %s\n" % change_id
      api.git.commit(message, api.path.join(*import_in.split('/')))
      api.git.push('HEAD:refs/for/master')

  # Decide which labels must be set.
  # * Dry-run mode: just CQ+1.
  # * Production mode: CQ+2 and CR+2 must be set to land the change.
  if dry_run:
    labels = {'Commit-Queue': 1}
  else:
    labels = {'Commit-Queue': 2, 'Code-Review': 2}

  # Activate CQ.
  # This call will return when Gerrit has set our desired labels on the change.
  # It will also always set the CQ process in motion.
  api.gerrit.set_review(
      'submit to commit queue',
      full_change_id,
      labels=labels,
  )

  # Poll gerrit to see if CQ was successful.
  # TODO(mknyszek): Figure out a cleaner solution than polling.
  for i in range(int(poll_timeout_secs/poll_interval_secs)):
    # Check the status of the CL.
    with api.context(infra_steps=True):
      change = api.gerrit.change_details('check if done (%d)' % i, full_change_id)

    # If the CQ label is un-set, then that means either:
    # * CQ failed (production mode), or
    # * CQ finished (dry-run mode).
    #
    # 'recommended' and 'approved' are objects that appear for a label if
    # somebody gave the label a positive vote (maximum vote (+2) for approved,
    # non-maximum (+1) for 'recommended') and contains the information of one
    # reviewer who gave this vote. There are 4 different states for a label in
    # this sense: 'rejected', 'approved', 'disliked', and 'recommended'. For a
    # given label, only one of these will be shown if the label has any votes
    # in priority order 'rejected' > 'approved' > 'disliked' > 'recommended'.
    # Unfortunately, this is the absolute simplest way to check this. Gerrit
    # provides an 'all' field that contains every vote, but iterating over
    # every vote, or operating under the assumption that there's at least one
    # causes more error cases.
    #
    # Read more at:
    # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#get-change-detail

    # In dry-run mode...
    if dry_run:
      # If CQ drops the CQ+1 label (i.e. 'recommended' state), then that means
      # CQ finished trying. CQ will always remove the CQ+1 label when it's
      # finished, regardless of success or failure.
      if 'recommended' not in change['labels']['Commit-Queue']:
        api.gerrit.abandon('abandon roll: dry run complete', full_change_id)
        return

    # In production mode...
    else:
      # If it merged, we're done!
      if change['status'] == 'MERGED':
        return

      # If CQ drops the CQ+2 label at any point (i.e. 'approved' state), then
      # that always means CQ has failed. CQ will always remove the CQ+2 label
      # when it fails, and it will never remove it on success.
      #
      # Note: Because CQ won't unset the the CQ+2 label when it merges, there's
      # no chance that we might see that the CL hasn't merged with the CQ+2
      # label unset on a successful CQ.
      if 'approved' not in change['labels']['Commit-Queue']:
        api.gerrit.abandon('abandon roll: CQ failed', full_change_id)
        raise api.step.StepFailure('Failed to roll changes: CQ failure.')

    # If none of the terminal conditions above were reached (that is, there were
    # no label changes from what we initially set, and the change has not
    # merged), then we should wait for |poll_interval_secs| before trying again.
    # TODO(mknyszek): Mock sleep so we're not actually sleeping during tests.
    time.sleep(poll_interval_secs)

  raise api.step.InfraFailure('Failed to roll changes: roller timed out.')


def GenTests(api):
  # Step data intended to be substituted in when a new change is created. This
  # provides an incomplete mock Gerrit change (as JSON) to the result of
  # api.gerrit.change_create() so that the auto-roller can move forward with
  # 'id' and 'change_id' in testing. For more information on the structure of
  # this see:
  # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
  new_change_data = api.step_data(
    'create new change',
    api.json.output({
      'id': 'beep%2Fboop~master~abc123',
      'change_id': 'abc123',
    }),
  )

  # Mock step data intended to be substituted as the result of the first check
  # during polling. It indicates a success, and should end polling.
  success_step_data = api.step_data('check if done (0)', api.json.output({
    'status': 'MERGED',
    'labels': {'Commit-Queue': {'approved':{}}}
  }))

  # Test a successful roll of zircon into garnet.
  yield (api.test('zircon') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + new_change_data + success_step_data)

  # Test a successful roll of garnet into peridot.
  yield (api.test('garnet') +
         api.properties(project='peridot',
                        manifest='manifest/minimal',
                        import_in='manifest/peridot',
                        import_from='garnet',
                        remote='https://fuchsia.googlesource.com/peridot',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + new_change_data + success_step_data)

  # Test a successful roll of peridot into topaz.
  yield (api.test('peridot') +
         api.properties(project='topaz',
                        manifest='manifest/minimal',
                        import_in='manifest/topaz',
                        import_from='peridot',
                        remote='https://fuchsia.googlesource.com/topaz',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + new_change_data + success_step_data)

  # Test a failure to roll zircon into garnet because CQ failed. The
  # Commit-Queue label is unset at the first check during polling.
  yield (api.test('zircon_cq_failure') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + new_change_data +
         api.step_data('check if done (0)', api.json.output({
             'status': 'NEW',
             'labels': {'Commit-Queue': {}}
         })))

  # Test a dry-run of the auto-roller for rolling zircon into garnet. We
  # substitute in mock data for the first check that the CQ dry-run completed by
  # unsetting the CQ label to indicate that the CQ dry-run finished.
  yield (api.test('zircon_dry_run') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        dry_run=True,
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + new_change_data +
         api.step_data('check if done (0)', api.json.output({
             'status': 'NEW',
             'labels': {'Commit-Queue': {}}
         })))

  # Test a failure to roll zircon because the auto-roller timed out. Sets the
  # poll_timeout to be very close to the poll_interval so only one check is
  # made. Here, we substitute in mock data that indicates CQ is still running,
  # but since we only try once, we will time out.
  yield (api.test('zircon_timeout') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        dry_run=True,
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.0015) +
         api.gitiles.log('log', 'A') + new_change_data +
         api.step_data('check if done (0)', api.json.output({
             'status': 'NEW',
             'labels': {
                 'Commit-Queue': {
                     'recommended': {}
                 }
             }
         })))
