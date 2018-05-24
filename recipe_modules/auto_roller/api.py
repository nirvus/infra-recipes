# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


UPSTREAM_REF = 'master'


class CQResult(object):
  """Represents the result of waiting for CQ to complete."""

  # CQ completed successfully.
  SUCCESS = 1

  # CQ tryjobs failed.
  FAILURE = 2

  # Timed out waiting for CQ to finish.
  TIMEOUT = 3


class AutoRollerApi(recipe_api.RecipeApi):
  """API for writing auto-roller recipes."""

  def __init__(self, poll_interval_secs, poll_timeout_secs, *args, **kwargs):
    # poll_interval_secs and poll_timeout_secs are input properties which come
    # from __init__.PROPERTIES in this directory.
    super(AutoRollerApi, self).__init__(*args, **kwargs)
    # The name of the link to the Gerrit change created for a roll.  This is
    # displayed in the CQ failure error message to help others understand where
    # to look when debugging failed rolls.
    self._gerrit_link_name = 'gerrit link'
    self._poll_interval_secs = poll_interval_secs
    self._poll_timeout_secs = poll_timeout_secs

  @property
  def poll_interval_secs(self):
    """Returns how many seconds roll() will wait in between each poll.

    Defined by the input property with the same name.
    """
    return self._poll_interval_secs

  @property
  def poll_timeout_secs(self):
    """Returns how many seconds roll() will poll for.

    Defined by the input property with the same name.
    """
    return self._poll_timeout_secs

  def _repo_has_uncommitted_files(self, repo_dir, check_untracked):
    """Checks whether the git repository at repo_dir has any changes.

    Args:
      repo_dir (Path): Path to the git repository.
      check_untracked (bool): Whether to include untracked files in the check.

    Returns:
      True if there are, and False if not.
    """
    args = ['--modified', '--deleted', '--exclude-standard']
    if check_untracked:
      args.append('--others')
    with self.m.context(cwd=repo_dir):
      step_result = self.m.git('ls-files', *args,
          name='check for no-op commit',
          stdout=self.m.raw_io.output(),
          step_test_data=lambda: self.m.raw_io.test_api.stream_output('hello'))
      step_result.presentation.logs['stdout'] = step_result.stdout.split('\n')
    return bool(step_result.stdout.strip())

  def _create_and_push_change(self, gerrit_project, repo_dir, commit_message,
                              commit_untracked):
    """Creates a Gerrit change containing modified files under repo_dir.

    Returns the unique Gerrit change ID for the newly created change.
    """

    # Create a new change for the roll.
    change = self.m.gerrit.create_change(
        'create new change',
        gerrit_project,
        commit_message,
        # TODO(mknyszek): Support branches other than UPSTREAM_REF when there's a
        # use-case for it.
        UPSTREAM_REF,
        # Step data intended to be substituted in when a new change is created. This
        # provides an incomplete mock Gerrit change (as JSON) to the result of
        # api.gerrit.change_create() so that the auto-roller can move forward with
        # 'id' and 'change_id' in testing. For more information on the structure of
        # this see:
        # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#change-info
        test_data=self.m.json.test_api.output({
          'id': 'beep%2Fboop~master~abc123',
          'change_id': 'abc123',
        }),
    )

    # NOTE: The project in a change_id may contain characters which are URL
    # encoded by gerrit (for example, '/'). This gets re-encoded by the
    # gerrit client underlying the gerrit recipe module for security, leading
    # to some strange results. By decoding first using self.m.url.unquote, we prevent
    # this from happening.

    # Represents the unique change ID for this change, usually of the form
    # <project>~<branch>~<change id> and is necessary for any API calls.
    full_change_id = self.m.url.unquote(change['id'])

    # Represents the change ID used in commit messages, which may not be
    # unique across projects and branches, but is useful for anything
    # UI-related.
    change_id = self.m.url.unquote(change['change_id'])

    # Surface a link to the change by querying gerrit for the change ID. If
    # it's the only commit with that change ID (highly likely) then it will
    # open it automatically. Unfortunately the unique change ID doesn't
    # exhibit this same behavior, so we avoid using it.
    self.m.step.active_result.presentation.links[self._gerrit_link_name] = self._gerrit_link(
      change_id)

    with self.m.context(cwd=repo_dir):
      # Update message with a Change-Id line and push the roll.
      updated_message = commit_message + ("\nChange-Id: %s\n" % change_id)
      if commit_untracked:
        self.m.git.commit(message=updated_message, all_files=True)
      else:
        self.m.git.commit(message=updated_message, all_tracked=True)
      self.m.git.push('HEAD:refs/for/%s' % UPSTREAM_REF)

    return full_change_id

  def _trigger_cq(self, change_id, dry_run):
    """Triggers CQ for the given change_id."""
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
    self.m.gerrit.set_review(
        'submit to commit queue',
        change_id,
        labels=labels,
    )

  def _wait_for_cq(self, change_id, dry_run):
    """Polls gerrit to see if CQ was successful.

    Returns a CQResult representing the status of CQ.
    """
    # TODO(mknyszek): Figure out a cleaner solution than polling.
    for i in range(int(self.poll_timeout_secs/self.poll_interval_secs)):
      # Check the status of the CL.
      with self.m.context(infra_steps=True):
        change = self.m.gerrit.change_details('check if done (%d)' % i, change_id)

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
      # https://gerrit-review.googlesource.com/Documentation/rest-self.m-changes.html#get-change-detail

      # In dry-run mode...
      if dry_run:
        # If CQ drops the CQ+1 label (i.e. 'recommended' state), then that means
        # CQ finished trying. CQ will always remove the CQ+1 label when it's
        # finished, regardless of success or failure.
        if 'recommended' not in change['labels']['Commit-Queue']:
          return CQResult.SUCCESS

      # In production mode...
      else:
        # If it merged, we're done!
        if change['status'] == 'MERGED':
          return CQResult.SUCCESS

        # If CQ drops the CQ+2 label at any point (i.e. 'approved' state), then
        # that always means CQ has failed. CQ will always remove the CQ+2 label
        # when it fails, and it will never remove it on success.
        #
        # Note: Because CQ won't unset the the CQ+2 label when it merges, there's
        # no chance that we might see that the CL hasn't merged with the CQ+2
        # label unset on a successful CQ.
        if 'approved' not in change['labels']['Commit-Queue']:
          return CQResult.FAILURE

      # If none of the terminal conditions above were reached (that is, there were
      # no label changes from what we initially set, and the change has not
      # merged), then we should wait for |poll_interval_secs| before trying again.
      self.m.time.sleep(self.poll_interval_secs)

    return CQResult.TIMEOUT

  def attempt_roll(self, gerrit_project, repo_dir, commit_message, commit_untracked=False,
                   dry_run=False):
    """Attempts to submit local edits via the CQ.

    It additionally has two modes of operation, dry-run mode and production mode.
    The precise steps it performs are as follows:

     * Create a patch in Gerrit and grab Change ID
     * Create a patch locally with Change ID
     * Push local patch to Gerrit
     * Production mode:
       * Set labels Code-Review+2 and Commit-Queue+2 on Gerrit patch
       * Wait for CQ to finish tryjobs and either merge the change or
         remove the label Commit-Queue+2 (failed tryjobs)
       * Abandon the change if the tryjobs failed
     * Dry-run Mode:
       * Set label Commit-Queue+1 on Gerrit patch
       * Wait for CQ to finish tryjobs and remove label Commit-Queue+1
       * Abandon the change to clean up

    It assumes that repo_dir contains unstaged changes to only tracked files.

    Args:
      gerrit_project (str): The name of the project to roll to in Gerrit, which
        is local to current Gerrit host as defined by api.gerrit.host(). For
        example, "garnet" would be a valid gerrit_project for
        fuchsia-review.googlesource.com.
      repo_dir (Path): The path to the directory containing a local copy of the
        git repo with changes that will be rolled.
      commit_message (str): The commit message for the roll. Note that this method will
        automatically append a Gerrit Change ID to the change. Also, it may be a
        multiline string (embedded newlines are allowed).
      commit_untracked (bool): Whether to commit untracked files as well.
      dry_run (bool): Whether to execute this method in dry_run mode.
    """
    self.m.gerrit.ensure_gerrit()

    # Check to see if there are actually any changes in repo_dir before
    # continuing.
    if not self._repo_has_uncommitted_files(repo_dir, commit_untracked):
      self.m.step('no changes to roll', None)
      return

    # Create the change both locally and remotely and push.
    change_id = self._create_and_push_change(
        gerrit_project=gerrit_project,
        repo_dir=repo_dir,
        commit_message=commit_message,
        commit_untracked=commit_untracked,
    )

    # Trigger CQ for the change ID.
    self._trigger_cq(change_id, dry_run)

    # Wait for CQ to complete.
    result = self._wait_for_cq(change_id, dry_run)

    # Interpret the result and finish.
    if dry_run and result == CQResult.SUCCESS:
      # Only abandon the roll on success if it was a dry-run.
      self.m.gerrit.abandon('abandon roll: dry run complete', change_id)
    elif result == CQResult.FAILURE:
      self._abandon_change_and_fail(reason='CQ failed', change_id=change_id)
    elif result == CQResult.TIMEOUT:
      self._abandon_change_and_fail(reason='auto-roller timeout', change_id=change_id)

  def _abandon_change_and_fail(self, reason, change_id):
    self.m.gerrit.abandon('abandon roll: ' + reason, change_id)
    gerrit_link = self._gerrit_link(change_id)
    self.m.step.active_result.presentation.links[self._gerrit_link_name] = self._gerrit_link(
      change_id)

    raise self.m.step.StepFailure(
      'Failed to roll changes: {reason}.\n\n'
      'See the link titled "{link}" in the build console to access the Gerrit '
      'change, and the failed tryjobs.'.format(
          reason=reason, link=self._gerrit_link_name,
      ))


  def _gerrit_link(self, change_id):
    return self.m.url.join(self.m.gerrit.host, 'q', change_id)
