# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import itertools
import re

from recipe_engine import recipe_api

class GitApi(recipe_api.RecipeApi):
  """GitApi provides support for Git."""

  _GIT_HASH_RE = re.compile('[0-9a-f]{40}', re.IGNORECASE)

  def __init__(self, *args, **kwargs):
    super(GitApi, self).__init__(*args, **kwargs)

  def __call__(self, *args, **kwargs):
    """Return a git command step."""
    name = kwargs.pop('name', 'git ' + args[0])
    git_cmd = ['git']
    for k, v in sorted(kwargs.pop('config', {}).iteritems()):
      git_cmd.extend(['-c', '%s=%s' % (k, v)])
    return self.m.step(name, git_cmd + list(args), **kwargs)

  def checkout(self, url, path=None, ref=None, recursive=False,
               submodules=True, submodule_force=False, remote='origin',
               file=None, **kwargs):
    """Checkout a given ref and return the checked out revision.

    Args:
      url (str): url of remote repo to use as upstream
      path (Path): directory to clone into
      ref (str): ref to fetch and check out
      recursive (bool): whether to recursively fetch submodules or not
      submodules (bool): whether to sync and update submodules or not
      submodule_force (bool): whether to update submodules with --force
      remote (str): name of the remote to use
      file (str): optional path to a single file to checkout
    """
    if not path:
      path = url.rsplit('/', 1)[-1]
      if path.endswith('.git'):  # https://host/foobar.git
        path = path[:-len('.git')]
      path = path or path.rsplit('/', 1)[-1] # ssh://host:repo/foobar/.git
      path = self.m.path['start_dir'].join(path)

    self.m.file.ensure_directory('makedirs', path)

    with self.m.context(cwd=path):
      if self.m.path.exists(path.join('.git')): # pragma: no cover
        self('config', '--remove-section', 'remote.%s' % remote, **kwargs)
      else:
        self('init', **kwargs)
      self('remote', 'add', remote or 'origin', url)

      if not ref:
        fetch_ref = self.m.properties.get('branch') or 'master'
        checkout_ref = 'FETCH_HEAD'
      elif self._GIT_HASH_RE.match(ref):
        fetch_ref = ''
        checkout_ref = ref
      elif ref.startswith('refs/heads/'):
        fetch_ref = ref[len('refs/heads/'):]
        checkout_ref = 'FETCH_HEAD'
      else:
        fetch_ref = ref
        checkout_ref = 'FETCH_HEAD'
      fetch_args = [x for x in (remote, fetch_ref) if x]
      if recursive:
        fetch_args.append('--recurse-submodules')
      self('fetch', *fetch_args, **kwargs)
      if file:
        self('checkout', '-f', checkout_ref, '--', file, **kwargs)
      else:
        self('checkout', '-f', checkout_ref, **kwargs)
      step = self('rev-parse', 'HEAD', stdout=self.m.raw_io.output(),
                  step_test_data=lambda:
                      self.m.raw_io.test_api.stream_output('deadbeef'))
      sha = step.stdout.strip()
      step.presentation.properties['got_revision'] = sha
      self('clean', '-f', '-d', '-x', **kwargs)
      if submodules:
        self('submodule', 'sync', name='submodule sync')
        submodule_update_args = ['--init']
        if recursive:
          submodule_update_args.append('--recursive')
        if submodule_force:
          submodule_update_args.append('--force')
        self('submodule', 'update', *submodule_update_args,
             name='submodule update', **kwargs)
      return sha

  def commit(self, message, files=(), all_tracked=False, all_files=False,
             **kwargs):
    """Runs git commit in the current working directory.
    Args:
      message (str): The message to attach to the commit.
      files (seq[Path]): The set of files containing changes to commit.
      all_tracked (bool): Stage all tracked files before committing. If True,
        files must be empty and all_files must be False.
      all_files (bool): Stage all files (even untracked) before committing. If
        True, files must be empty and all_tracked must be False.
    """
    if all_tracked:
      assert not all_files
      assert not files
      return self('commit', '-m', message, '-a', **kwargs)
    elif all_files:
      assert not files
      self('add', '-A')
      return self('commit', '-m', message, **kwargs)
    return self('commit', '-m', message, *files, **kwargs)

  def push(self, ref, remote='origin', **kwargs):
    return self('push', remote, ref, **kwargs)

  def rebase(self, branch='master', remote='origin', **kwargs):
    """Run rebase HEAD onto branch"""
    try:
      self('rebase', '%s/%s' % (remote, branch), **kwargs)
    except self.m.step.StepFailure: # pragma: no cover
      self('rebase', '--abort', **kwargs)
      raise

  def get_hash(self, commit='HEAD', **kwargs):
    """Find and return the hash of the given commit."""
    return self('show', commit, '--format=%H', '-s',
                step_test_data=lambda:
                    self.m.raw_io.test_api.stream_output('deadbeef'),
                stdout=self.m.raw_io.output(), **kwargs).stdout.strip()

  def get_timestamp(self, commit='HEAD', test_data=None, **kwargs):
    """Find and return the timestamp of the given commit."""
    return self('show', commit, '--format=%at', '-s',
                step_test_data=lambda:
                    self.m.raw_io.test_api.stream_output('1473312770'),
                stdout=self.m.raw_io.output(), **kwargs).stdout.strip()
