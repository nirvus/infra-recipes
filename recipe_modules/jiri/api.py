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
          # Specify a path under start_dir to satisfy consumers that expect a
          # "realistic" path, such as LUCI's PathApi.abs_to_path.
          'path': str(self.m.path['start_dir'].join('path','to',p)),
          'remote': 'https://fuchsia.googlesource.com/' + p,
          'revision': 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127',
          'current_branch': '',
          'branches': [ '(HEAD detached at c22471f)' ]
      } for p in projects]

    return self(*cmd, step_test_data=lambda: self.test_api.project(test_data))

  def update(self, gc=False, rebase_tracked=False, local_manifest=False,
             run_hooks=True, snapshot=None, attempts=3, **kwargs):
    cmd = [
      'update',
      '-autoupdate=false',
      '-attempts=%d' % attempts,
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

  def run_hooks(self, local_manifest=False, attempts=3):
    cmd = [
      'run-hooks',
      '-attempts=%d' % attempts,
    ]
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
    """Creates a step to edit a Jiri manifest.

    Args:
      manifest (str): Path to the manifest to edit relative to the project root.
        e.g. "manifest/zircon"
      projects (List): A heterogeneous list whose entries are either:
        * A string representing the name of a project to edit.
        * A (name, revision) tuple representing a project to edit.
      imports (List): The same as projects, except each list entry represents an
        import to edit.

    Returns:
      A step to edit the manifest.
    """

    cmd = [
      'edit',
      '-json-output', self.m.json.output(),
    ]
    # Test data consisting of (name, revision) tuples of imports to edit in the
    # given manifest.
    test_imports = []

    if imports:
      for i in imports:
        if type(i) is str:
          cmd.extend(['-import', i])
          test_imports.append((i, "HEAD"))
        elif type(i) is tuple:
          cmd.extend(['-import', '%s=%s' % i])
          test_imports.append(i)

    # Test data consisting of (name, revision) tuples of projects to edit in the
    # given manifest.
    test_projects = []

    if projects:
      for p in projects:
        if type(p) is str:
          cmd.extend(['-project', p])
          test_projects.append((p, "HEAD"))
        elif type(p) is tuple:
          cmd.extend(['-project', '%s=%s' % p])
          test_projects.append(p)
    cmd.extend([manifest])

    # Generate test data
    if test_data is None:
      test_data = self.test_api.example_edit(
          imports=test_imports,
          projects=test_projects,
      )

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
               patch_gerrit_url=None, patch_project=None, timeout_secs=None):
    self.init()
    self.import_manifest(manifest, remote, project)
    # Note that timeout is not a jiri commandline argument, but a param
    # that will get passed to self.m.step() via kwargs.
    self.update(run_hooks=False, timeout=timeout_secs)
    if patch_ref:
      self.patch(patch_ref, host=patch_gerrit_url, project=patch_project, rebase=True)
    self.run_hooks()

    manifest = self.source_manifest()
    self.m.source_manifest.set_json_manifest('checkout', manifest)

  def read_manifest_project(self, manifest, project_name):
    """Reads information about a <project> from a manifest file.

    Args:
      manifest (str|Path): Path to the manifest file.
      project_name (str): The name of the project.

    Returns:
      A dict containing the project fields. Any missing values are left empty.
      Fields are accessed using their manifest attribute-names.  For example:

          print(project['remote']) # https://fuchsia.googlesource.com/my_project
    """

    # This is a Go template matching the schema in pkg/text/template. See docs
    # for `manifest` for more details.  We format the template as JSON to make
    # it easy to parse into a dict.  Add fields to this template as-needed.
    template='''
    {
      "gerrithost": "{{.GerritHost}}",
      "githooks": "{{.GitHooks}}",
      "historydepth": "{{.HistoryDepth}}",
      "name": "{{.Name}}",
      "path": "{{.Path}}",
      "remote": "{{.Remote}}",
      "remotebranch": "{{.RemoteBranch}}",
      "revision": "{{.Revision}}",
    }
    '''
    result = self.__manifest(
        manifest=manifest,
        element_name=project_name,
        template=template,
        step_test_data=lambda: self.m.json.test_api.output_stream(
            self.m.json.dumps(self.test_api.example_json_project)),
        stdout=self.m.json.output(),
    ).stdout
    return self.m.json.loads(result)


  def __manifest(self, manifest, element_name, template, **kwargs):
    """Reads information about a <project> or <import> from a manifest file.

    The template argument is a Go template string matching the schema defined in
    pkg/text/template: https://golang.org/pkg/text/template/#hdr-Examples.

    Any of a project's or import's fields may be specified in the template. See
    https://fuchsia.googlesource.com/jiri/+/master/project/project.go for a list
    of all project fields.  For a list of all import fields, see:
    https://fuchsia.googlesource.com/jiri/+/master/project/manifest.go.

    Example Usage:

      # Read the remote= attribute of some <project>.
      #
      # Example output: https://code.com/my_project.git
      __manifest(manifest='manifest', element_name='my_project',
          template='{{.Remote}}')

      # Read the remote= and path= attributes from some <import>, and
      # format the output as "$remote is cloned to $path".
      #
      # Example output: https://code.com/my_import.git is cloned to /my_import.
      __manifest(manifest='manifest', element_name='my_import',
          template='{{.Remote}}) is cloned to {{.Path}}')

    Args:
      manifest (str|Path): Path to the manifest file.
      element_name (str): The name of the <project> or <import> to read from.
      template (str): A Go template string matching pkg/text/template.

    Returns:
      The filled-in template string.  If the <project> or <import> did not have
      a value for some field in the template, the empty string is filled-in for
      that field.
    """
    return self(
      'manifest',
      '-element', element_name,
      '-template', template,
      manifest,
      **kwargs
    )

