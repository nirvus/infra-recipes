# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from urlparse import urlparse


class CheckoutApi(recipe_api.RecipeApi):
  """An abstraction over how Jiri checkouts are created during Fuchsia CI/CQ builds"""

  def __call__(self,
               manifest,
               remote,
               project=None,
               build_input=None,
               timeout_secs=None,
               run_hooks=True,
               override=False):
    """Initializes and populates a jiri checkout from a remote manifest.

    Emits a source manifest for the build.

    Args:
        manifest (str): Relative path to the manifest in the remote repository.
        remote (str): URL to the remote repository.
        project (str): The name that jiri should assign to the project.
        build_input (buildbucket.build_pb2.Build.Input): The input to a buildbucket
            build.
        timeout_secs (int): A timeout for jiri update in seconds.
        run_hooks (bool): Whether or not to run the hooks.
        override (bool): Whether to override the imported manifest with a commit's
            given revision.
    """
    self.m.jiri.ensure_jiri()
    self.m.jiri.init()

    if build_input and build_input.gerrit_changes:
      assert len(build_input.gerrit_changes) == 1
      self.from_patchset(
          manifest=manifest,
          remote=remote,
          project=project,
          run_hooks=run_hooks,
          timeout_secs=timeout_secs,
          gerrit_change=build_input.gerrit_changes[0])
    else:
      commit = None
      if build_input and build_input.gitiles_commit.id:
        commit = build_input.gitiles_commit

      self.from_commit(
          manifest=manifest,
          remote=remote,
          commit=commit,
          project=project,
          run_hooks=run_hooks,
          override=override,
          timeout_secs=timeout_secs)

    self.m.jiri.emit_source_manifest()

  def from_patchset(self, manifest, remote, project, run_hooks, timeout_secs,
                    gerrit_change):
    """Initializes and populates a Jiri checkout from a remote manifest and Gerrit change.

    Args:
        manifest (str): Relative path to the manifest in the remote repository.
        remote (str): URL to the remote repository.
        project (str): The name that jiri should assign to the project.
        build_input (buildbucket.build_pb2.Build.Input): The input to a buildbucket
            build.
        timeout_secs (int): A timeout for jiri update in seconds.
        gerrit_change: An element from buildbucket.build_pb2.Build.Input.gerrit_changes.
    """
    self.m.gerrit.ensure_gerrit()
    details = self._get_change_details(gerrit_change)

    self.m.jiri.import_manifest(
        manifest,
        remote,
        name=project,
        revision='HEAD',
        remote_branch=details['branch'])
    self.m.jiri.update(run_hooks=False, timeout=timeout_secs)

    current_revision = details['current_revision']
    patch_ref = details['revisions'][current_revision]['ref']
    self.m.jiri.patch(
        patch_ref,
        host='https://%s' % gerrit_change.host,
        project=gerrit_change.project,
        rebase=True,
    )

    self.m.jiri.update(
        gc=True,
        rebase_tracked=True,
        local_manifest=True,
        run_hooks=False,
        timeout=timeout_secs)
    if run_hooks:
      self.m.jiri.run_hooks(local_manifest=True)

  def from_commit(self, manifest, remote, commit, project, run_hooks, override,
                  timeout_secs):
    """Initializes and populates a Jiri checkout from a remote manifest and Gerrit change.

    Args:
        manifest (str): Relative path to the manifest in the remote repository.
        remote (str): URL to the remote repository.
        project (str): The name that jiri should assign to the project.
        remote (str): The remote git repository.
        commit: Commit information derived from
            buildbucket.build_pb2.Build.Input.gitiles_commit.
        timeout_secs (int): A timeout for jiri update in seconds.
        run_hooks (bool): Whether or not to run the hooks.
        override (bool): Whether to override the imported manifest with a commit's
            given revision.
    """
    revision = commit.id if commit else 'HEAD'
    if override and commit:
      self.m.jiri.import_manifest(
          manifest, remote, name=project, revision='HEAD')

      # Note that in order to identify a project to override, jiri keys on
      # both the project name and the remote source repository (not to be
      # confused with `remote`, the manifest repository).
      # We reconstruct the source repository in a scheme-agnostic manner.
      manifest_remote_url = urlparse(remote)
      project_remote = '%s://%s/%s' % (
          manifest_remote_url.scheme,
          manifest_remote_url.netloc,
          commit.project,
      )
      self.m.jiri.override(
          project=commit.project, remote=project_remote, new_revision=revision)
    else:
      self.m.jiri.import_manifest(
          manifest, remote, name=project, revision=revision)

    self.m.jiri.update(run_hooks=False, timeout=timeout_secs)
    if run_hooks:
      self.m.jiri.run_hooks()

  def _get_change_details(self, gerrit_change):
    """Fetches the details of a Gerrit change"""
    return self.m.gerrit.change_details(
        name='get change details',
        change_id='%s~%s' % (
            gerrit_change.project,
            gerrit_change.change,
        ),
        gerrit_host='https://%s' % gerrit_change.host,
        query_params=['CURRENT_REVISION'],
        test_data=self.m.json.test_api.output({
            'branch': 'master',
            'current_revision': 'a1b2c3',
            'revisions': {
                'a1b2c3': {
                    'ref': 'refs/changes/00/100/5'
                }
            }
        }),
    )
