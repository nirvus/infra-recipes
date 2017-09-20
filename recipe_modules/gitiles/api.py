# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64

from recipe_engine import recipe_api


class GitilesApi(recipe_api.RecipeApi):
  """Module for polling a Git repository using the Gitiles web interface."""

  def __init__(self, *args, **kwargs):
    super(GitilesApi, self).__init__(*args, **kwargs)
    self._gitiles_path = None

  def ensure_gitiles(self, version=None):
    with self.m.step.nest('ensure_gitiles'):
      with self.m.context(infra_steps=True):
        gitiles_package = ('infra/tools/gitiles/%s' %
            self.m.cipd.platform_suffix())
        gitiles_dir = self.m.path['start_dir'].join('cipd', 'gitiles')

        self.m.cipd.ensure(
            gitiles_dir, {gitiles_package: version or 'latest'})
        self._gitiles_path = gitiles_dir.join('gitiles')

        return self._gitiles_path

  def refs(self, url, refspath='refs/heads', step_name='refs', test_data=[]):
    """Resolves each ref in a repository to git revision

    Args:
      url (str): URL of the remote repository.
      refspath (str): limits which refs to resolve.
    """
    assert self._gitiles_path
    assert refspath.startswith('refs')
    cmd = [
      self._gitiles_path,
      'refs',
      '-json-output', self.m.json.output(),
    ]
    cmd.extend([url, refspath])
    return self.m.step(
        step_name,
        cmd,
        step_test_data=test_data
    ).json.output

  def log(self, url, treeish, limit=0, step_name=None, test_data={}):
    """Returns the most recent commits for treeish object.

    Args:
      url (str): base URL of the remote repository.
      treeish (str): tree object identifier.
      limit (int): number of commits to limit the fetching to.
      step_name (str): custom name for this step (optional).
    """
    assert self._gitiles_path
    cmd = [
      self._gitiles_path,
      'log',
      '-json-output', self.m.json.output(),
    ]
    if limit:
      cmd.extend(['-limit', limit])
    cmd.extend([url, treeish])
    return self.m.step(
      step_name or 'gitiles log: %s' % treeish,
        cmd,
        step_test_data=test_data
    ).json.output

  def fetch(self, url, file_path, branch='master', step_name=None,
            timeout=None, test_data=None):
    """Downloads raw file content from a Gitiles repository.

    Args:
      url (str): base URL to the repository.
      file_path (str): relative path to the file from the repository root.
      branch (str): branch of the repository.
      step_name (str): custom name for this step (optional).
      timeout (int): number of seconds to wait before failing.

    Returns:
      Raw file content.
    """
    step_result = self.m.url.get_text(
        self.m.url.join(url, '+/%s/%s' % (branch, file_path)),
        step_name=step_name or 'fetch %s:%s' % (branch, file_path,),
        timeout=timeout, default_test_data=base64.b64encode(test_data))
    return base64.b64decode(step_result.output)
