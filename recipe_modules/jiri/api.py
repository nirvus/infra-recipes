# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

# Flags added to all jiri commands.
COMMON_FLAGS = [
    '-v',
    '-time',
]


class JiriApi(recipe_api.RecipeApi):
  """JiriApi provides support for Jiri managed checkouts."""

  def __init__(self, *args, **kwargs):
    super(JiriApi, self).__init__(*args, **kwargs)
    self._jiri_executable = None

  def __call__(self, *args, **kwargs):
    """Return a jiri command step."""
    subcommand = args[0]  # E.g., 'init' or 'update'
    flags = COMMON_FLAGS + list(args[1:])

    assert self._jiri_executable
    full_cmd = [self._jiri_executable, subcommand] + flags

    name = kwargs.pop('name', 'jiri ' + subcommand)
    return self.m.step(name, full_cmd, **kwargs)

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
      '-analytics-opt=false',
      '-rewrite-sso-to-https=true',
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
          'name': p,
          'path': '/path/to/' + p,
          'remote': 'https://fuchsia.googlesource.com/' + p,
          'revision': 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127',
          'current_branch': '',
          'branches': [ '(HEAD detached at c22471f)' ]
      } for p in projects]

    return self(*cmd, step_test_data=lambda: self.test_api.project(test_data))

  def update(self, gc=False, rebase_tracked=False, local_manifest=False,
             run_hooks=True, snapshot=None, **kwargs):
    cmd = [
      'update',
      '-autoupdate=false',
    ]
    if gc:
      cmd.append('-gc=true')
    if rebase_tracked:
      cmd.append('-rebase-tracked')
    if local_manifest:
      cmd.append('-local-manifest=true')
    if not run_hooks:
      cmd.append('-run-hooks=false')
    if snapshot is not None:
      cmd.append(snapshot)

    return self(*cmd, **kwargs)

  def run_hooks(self, local_manifest=False):
    cmd = ['run-hooks']
    if local_manifest:
      cmd.append('-local-manifest=true')
    return self(*cmd)

  def clean(self, all=False, **kwargs):
    cmd = [
      'project',
      '-clean-all' if all else '-clean',
    ]
    kwargs.setdefault('name', 'jiri project clean')

    return self(*cmd, **kwargs)

  def import_manifest(self, manifest, remote, name=None, overwrite=False, **kwargs):
    cmd = [ 'import' ]
    if name:
      cmd.extend(['-name', name])
    if overwrite:
      cmd.extend(['-overwrite=true'])
    cmd.extend([manifest, remote])

    return self(*cmd, **kwargs)

  def edit_manifest(self, manifest, projects=None, imports=None, test_data=None):
    cmd = [
      'edit',
      '-json-output', self.m.json.output(),
    ]
    if imports:
      for i in imports:
        if type(i) is str:
          cmd.extend(['-import', i])
        elif type(i) is tuple:
          cmd.extend(['-import', '%s=%s' % i])
    if projects:
      for p in projects:
        if type(p) is str:
          cmd.extend(['-project', p])
        elif type(p) is tuple:
          cmd.extend(['-project', '%s=%s' % p])
    cmd.extend([manifest])
    if test_data is None:
      test_data = self.test_api.example_edit
    step = self(*cmd,
                step_test_data=lambda: self.m.json.test_api.output(test_data))
    return step.json.output

  def patch(self, ref, host=None, project=None, delete=False, force=False,
            rebase=False):
    cmd = [ 'patch' ]
    if host:
      cmd.extend(['-host', host])
    if project:
      cmd.extend(['-project', project])
    if delete:
      cmd.extend(['-delete=true'])
    if force:
      cmd.extend(['-force=true'])
    if rebase:  # pragma: no cover
      cmd.extend(['-rebase=true'])
    cmd.extend([ref])

    return self(*cmd)

  def snapshot(self, file=None, test_data=None, **kwargs):
    cmd = [
      'snapshot',
      self.m.raw_io.output(name='snapshot', leak_to=file),
    ]
    if test_data is None:
      test_data = self.test_api.example_snapshot
    step = self(*cmd, step_test_data=lambda: self.test_api.snapshot(test_data), **kwargs)
    return step.raw_io.output

  def source_manifest(self, file=None, test_data=None, **kwargs):
    cmd = [
      'source-manifest',
      self.m.json.output(name='source manifest', leak_to=file),
    ]
    if test_data is None:
      test_data = self.test_api.example_source_manifest
    step = self(*cmd, step_test_data=lambda: self.test_api.source_manifest(test_data), **kwargs)
    return step.json.output

  def checkout(self, manifest, remote, project=None, patch_ref=None,
               patch_gerrit_url=None, patch_project=None):
    self.init()
    self.import_manifest(manifest, remote, project)
    self.update(run_hooks=False)
    if patch_ref:
      self.patch(patch_ref, host=patch_gerrit_url, project=patch_project, rebase=True)
    self.run_hooks()

    manifest = self.source_manifest()
    self.m.source_manifest.set_json_manifest('checkout', manifest)
