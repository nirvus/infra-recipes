# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from urlparse import urlparse
import collections

# PatchInput describes the input to a `jiri patch` command. These are decoded from the
# list of JSON objects in a .patchfile (see below).
#
# Properties:
#   ref (str): The gerrit change ref (e.g refs/changes/aa/aabbcc/n)
#   host (str): The code review host (e.g. fuchsia-review.googlesource.com)
#   project (str): The patch project (e.g. garnet)
#
# Usage:
#   These inputs are typically specified within a .patchfile at the root of a project's
#   directory.  When checking out from a gerrit patchset (i.e. when running on CQ),
#   CheckoutApi will patch any changes listed in this file.
PatchInput = collections.namedtuple('PatchInput', 'ref host project')


class PatchFile:
  """A file used to patch one or more changes from unrelated projects into a workspace.

  The patchfile should contain a list of JSON objects with the following structure:

    [
        {
            "ref": "refs/changes/56/123456/3",
            "host": "fuchsia-review.googlesource.com",
            "project": "project",
        }
    ]
  """

  @staticmethod
  def from_json(js):
    patch_inputs = []
    for js_object in js:
      patch_inputs.append(PatchInput(**js_object))

    return PatchFile(patch_inputs)

  def __init__(self, patch_inputs):
    self.patch_inputs = patch_inputs

  @property
  def inputs(self):
    return self.patch_inputs

  def validate(self, gerrit_change):
    """Verifies the following about this PatchFile:

    1. No input overwrites the Gerrit change that is currently being tested.
    2. No two inputs patch over one another.

    Returns:
        A ValueError that should be raised as a StepFailure, if validation fails. Else
        None.
    """

    def create_key(project, host):
      """Produces a unique ID for a project + host combination."""
      return '%s/%s' % (project, host)

    # Maps validated PatchInput keys to their PatchInputs.
    validated = {}

    # The key for the original Gerrit change that is being tested.
    gerrit_patch_key = create_key(gerrit_change.project, gerrit_change.host)

    for patch_input in self.patch_inputs:
      patch_key = create_key(patch_input.project, patch_input.host)

      # User cannot use the patchfile to overwrite the original gerrit change.
      if patch_key == gerrit_patch_key:
        return ValueError((
            "This patch overwrites the original gerrit change: %s\n"
            "Inline this patch into the change instead of specifying in .patchfile"
        ) % str(patch_input))

      # User cannot patch multiple changes to the same project. Those changes should
      # be tested locally.
      if validated.get(patch_key, None):
        return ValueError((
            "Found patch that ovewrites a previous patch. These changes should be"
            "tested together locally instead of through the patchfile:\n"
            "Original:  %(original)s\nDuplicate: %(duplicate)s.") % dict(
                original=str(validated[patch_key]),
                duplicate=str(patch_input),
            ))

      validated[patch_key] = patch_input


class CheckoutApi(recipe_api.RecipeApi):
  """An abstraction over how Jiri checkouts are created during Fuchsia CI/CQ builds."""

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

    # Fetch the project and update.
    details = self._get_change_details(gerrit_change)
    self.m.jiri.import_manifest(
        manifest,
        remote,
        name=project,
        revision='HEAD',
        remote_branch=details['branch'])

    self.m.jiri.update(run_hooks=False, timeout=timeout_secs)

    # Patch the current Gerrit change.
    current_revision = details['current_revision']
    patch_ref = details['revisions'][current_revision]['ref']
    self.m.jiri.patch(
        patch_ref,
        host='https://%s' % gerrit_change.host,
        project=gerrit_change.project,
        rebase=True,
    )

    # Handle the patchfile, if present.
    self._apply_patchfile(gerrit_change)

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

  def _apply_patchfile(self, gerrit_change):
    """Parses and applies the patchfile for the given gerrit change."""

    # Verify the patchfile exists.
    patchfile_path = self.m.path['start_dir'].join(gerrit_change.project,
                                                   '.patchfile')
    if not self.m.path.exists(patchfile_path):
      return

    patch_file = self._parse_patchfile(patchfile_path)

    # Ensure patchfile is valid.
    validation_err = patch_file.validate(gerrit_change)
    if validation_err is not None:
      raise self.m.step.StepFailure(str(validation_err))

    for patch_input in patch_file.inputs:
      # Strip protocol if present.
      host = patch_input.host
      host_url = urlparse(host)
      if host_url.scheme:
        host = host_url.hostname

      # Patch in the change
      self.m.jiri.patch(
          ref=patch_input.ref,
          host='https://%s' % host,
          project=patch_input.project,
          rebase=True)

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

  def _parse_patchfile(self, patchfile_path):
    """Parses a .patchfile from the given path"""
    js = self.m.json.read(
        'read .patchfile',
        patchfile_path,
    ).json.output
    return PatchFile.from_json(js)
