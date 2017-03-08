# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class JiriApi(recipe_api.RecipeApi):
  """JiriApi provides support for Jiri managed checkouts."""

  def __init__(self, *args, **kwargs):
    super(JiriApi, self).__init__(*args, **kwargs)
    self._jiri_executable = None

  def __call__(self, *args, **kwargs):
    """Return a jiri command step."""
    assert self._jiri_executable
    name = kwargs.pop('name', 'jiri ' + args[0])
    jiri_cmd = [self._jiri_executable]
    return self.m.step(name, jiri_cmd + list(args), **kwargs)

  def ensure_jiri(self, version=None):
    with self.m.step.nest('ensure_jiri'):
      with self.m.step.context({'infra_step': True}):
        jiri_package = ('fuchsia/tools/jiri/%s' %
            self.m.cipd.platform_suffix())
        cipd_dir = self.m.path['start_dir'].join('cipd', 'jiri')

        self.m.cipd.ensure(cipd_dir,
                           {jiri_package: version or 'latest'})
        self._jiri_executable = cipd_dir.join('jiri')

        return self._jiri_executable

  @property
  def jiri(self):
    return self._jiri_executable

  def init(self, dir=None, **kwargs):
    cmd = [
      'init',
      '-cache', self.m.path['cache'].join('git'),
    ]
    if dir:
      cmd.append(dir)

    return self(*cmd, **kwargs)

  def project(self, *projects, **kwargs):
    cmd = [
      'project',
      'info',
      '-json-output', self.m.json.output(),
    ] + list(projects)
    kwargs.setdefault('name', 'jiri project info')

    return self(
        *cmd,
        step_test_data=lambda: self.test_api.example_project(projects),
        **kwargs
    )

  def update(self, gc=False, snapshot=None, **kwargs):
    cmd = [
      'update',
      '-autoupdate=false',
    ]
    if gc:
      cmd.extend(['-gc=true'])
    if snapshot is not None:
      cmd.append(snapshot)

    return self(*cmd, **kwargs)

  def clean_project(self, branches=False, **kwargs):
    cmd = [
      'project',
      'clean',
    ]
    if branches:
      cmd.extend(['-branches=true'])
    kwargs.setdefault('name', 'jiri project clean')

    return self(*cmd, **kwargs)

  def import_manifest(self, manifest, remote, overwrite=False, **kwargs):
    cmd = [ 'import' ]
    if overwrite:
      cmd.extend(['-overwrite=true'])
    cmd.extend([manifest, remote])

    return self(*cmd, **kwargs)

  def patch(self, ref, host=None, delete=False, force=False, rebase=False,
            **kwargs):
    cmd = [ 'patch' ]
    if host:
      cmd.extend(['-host', host])
    if delete:
      cmd.extend(['-delete=true'])
    if force:
      cmd.extend(['-force=true'])
    if rebase:
      cmd.extend(['-rebase=true'])
    cmd.extend([ref])

    return self(*cmd, **kwargs)

  def snapshot(self, file, step_test_data=None, **kwargs):
    return self(
        'snapshot', file,
        step_test_data=step_test_data or self.test_api.example_snapshot,
        **kwargs
    )
