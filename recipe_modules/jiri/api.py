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
      with self.m.context(infra_steps=True):
        jiri_package = ('fuchsia/tools/jiri/%s' %
            self.m.cipd.platform_suffix())
        cipd_dir = self.m.path['start_dir'].join('cipd', 'jiri')

        self.m.cipd.ensure(cipd_dir,
                           {jiri_package: version or 'stable'})
        self._jiri_executable = cipd_dir.join('jiri')

        return self._jiri_executable

  @property
  def jiri(self):
    return self._jiri_executable

  def init(self, dir=None, **kwargs):
    cmd = [
      'init',
      '-cache', self.m.path['cache'].join('git'),
      '-shared',
    ]
    if dir:
      cmd.append(dir)

    return self(*cmd, **kwargs)

  def project(self, projects, test_data=None):
    cmd = [
      'project',
      '-json-output', self.m.json.output(),
    ] + projects

    if test_data is None:
      test_data = [{
          "name": p,
          "path": "/path/to/" + p,
          "remote": "https://fuchsia.googlesource.com/" + p,
          "revision": "c22471f4e3f842ae18dd9adec82ed9eb78ed1127",
          "current_branch": "",
          "branches": [ "(HEAD detached at c22471f)" ]
      } for p in projects]

    return self(*cmd, step_test_data=lambda: self.test_api.project(test_data))

  def update(self, gc=False, snapshot=None, local_manifest=False, **kwargs):
    cmd = [
      'update',
      '-autoupdate=false',
    ]
    if gc:
      cmd.extend(['-gc=true'])
    if snapshot is not None:
      cmd.append(snapshot)
    if local_manifest:
      cmd.extend(['-local-manifest=true'])

    return self(*cmd, **kwargs)

  def clean(self, all=False, **kwargs):
    cmd = [
      'project',
      '-clean-all' if all else '-clean',
    ]
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
    if rebase:  # pragma: no cover
      cmd.extend(['-rebase=true'])
    cmd.extend([ref])

    return self(*cmd, **kwargs)

  def snapshot(self, file=None, test_data=None, **kwargs):
    cmd = [
      'snapshot',
      self.m.raw_io.output(leak_to=file),
    ]
    if test_data is None:
      test_data = self.test_api.example_snapshot
    step = self(*cmd, step_test_data=lambda: self.test_api.snapshot(test_data), **kwargs)
    return step.raw_io.output

  def checkout(self, manifest, remote, patch_ref=None, patch_gerrit_url=None):
    self.init()
    self.import_manifest(manifest, remote)
    self.update()
    if patch_ref:
      self.patch(patch_ref, host=patch_gerrit_url, rebase=True)

    # TODO(phosek): remove this once snapshot supports -source-manifest
    #step = self('snapshot',
    #  '-source-manifest', self.m.json.output(name='source manifest'),
    #  self.m.raw_io.output(),
    #  step_test_data=lambda: self.m.json.test_api.output(self.test_api.example_source_manifest, name='source manifest'))
    #manifest = step.json.output
    #self.m.source_manifest.set_json_manifest('checkout', manifest)
