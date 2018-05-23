# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Example recipe for auto-rolling."""


from recipe_engine.recipe_api import Property

DEPS = [
  'infra/auto_roller',
  'infra/git',
  'recipe_engine/path',
  'recipe_engine/properties',
]


PROPERTIES = {
  'project': Property(kind=str, help='Gerrit project', default=None),
  'remote': Property(kind=str, help='Remote repository'),
  'commit_untracked_files': Property(kind=bool,
                                     default=False,
                                     help='Whether to commit untracked files'),
  'dry_run': Property(kind=bool,
                      default=False,
                      help='Whether to dry-run the auto-roller (CQ+1 and abandon the change)'),
}


def RunSteps(api, project, remote, commit_untracked_files, dry_run):
  # Check out the repo.
  api.git.checkout(remote)

  # Do some changes to the repo.
  # ...

  # Land the changes.
  api.auto_roller.attempt_roll(
      gerrit_project=project,
      repo_dir=api.path['start_dir'].join(project),
      repo_url=remote,
      commit_message='hello world!',
      commit_untracked=commit_untracked_files,
      dry_run=dry_run,
  )


def GenTests(api):
  # Test a successful roll of zircon into garnet.
  yield (api.test('zircon') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.step_data('check if done (0)', api.auto_roller.success()))

  # Test a successful roll of zircon into garnet with the default poll
  # configuration.
  yield (api.test('zircon_default') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet') +
         api.step_data('check if done (0)', api.auto_roller.success()))

  # Test a successful roll of zircon into garnet with the default poll
  # configuration, and include untracked files.
  yield (api.test('zircon_untracked') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        commit_untracked_files=True) +
         api.step_data('check if done (0)', api.auto_roller.success()))

  # Test a failure to roll zircon into garnet because CQ failed. The
  # Commit-Queue label is unset at the first check during polling.
  yield (api.test('zircon_cq_failure') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.step_data('check if done (0)', api.auto_roller.failure()))

  # Test a dry-run of the auto-roller for rolling zircon into garnet. We
  # substitute in mock data for the first check that the CQ dry-run completed by
  # unsetting the CQ label to indicate that the CQ dry-run finished.
  yield (api.test('zircon_dry_run') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        dry_run=True,
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.step_data('check if done (0)', api.auto_roller.dry_run()))

  # Test a failure to roll zircon because the auto-roller timed out. Sets the
  # poll_timeout to be very close to the poll_interval so only one check is
  # made. Here, we substitute in mock data that indicates CQ is still running,
  # but since we only try once, we will time out.
  yield (api.test('zircon_timeout') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.0015) +
         api.step_data('check if done (0)', api.auto_roller.timeout()))

  # Test a successful roll of zircon with integral arguments to poll_*_secs.
  # This tests for any regression in supporting integral values for
  # polling-related properties.
  yield (api.test('zircon_integral_poll_secs') +
         api.properties(project='garnet',
                        remote='https://fuchsia.googlesource.com/garnet',
                        poll_interval_secs=1,
                        poll_timeout_secs=1) +
         api.step_data('check if done (0)', api.auto_roller.success()))
