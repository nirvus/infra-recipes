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
        jiri_package = ('fuchsia/tools/jiri/%s' % self.m.cipd.platform_suffix())
        cipd_dir = self.m.path['start_dir'].join('cipd', 'jiri')

        self.m.cipd.ensure(cipd_dir, {jiri_package: version or 'stable'})
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
        '-cache',
        self.m.path['cache'].join('git'),
        '-shared',
    ]
    if dir:
      cmd.append(dir)

    return self(*cmd, **kwargs)

  def project(self, projects=[], out=None, test_data=None):
    """
    Args:
      projects (List): A heterogeneous list of strings representing the name of
        projects to list info about (defaults to all).
      out (str): Path to write json results to, with the following schema:
        [
          {
            "name": "zircon",
            "path": "local/path/to/zircon",
            "relativePath": "zircon",
            "remote": "https://fuchsia.googlesource.com/zircon",
            "revision": "af8fd6138748bc11d31a5bde3303cdc19c7e04e9",
            "current_branch": "master",
            "branches": [
              "master"
            ]
          }
          ...
        ]


    Returns:
      A step to provide structured info on existing projects and branches.
    """
    cmd = [
        'project',
        '-json-output',
        self.m.json.output(leak_to=out),
    ] + projects

    if test_data is None:
      test_data = [
          {
              'name': p,
              # Specify a path under start_dir to satisfy consumers that expect a
              # "realistic" path, such as LUCI's PathApi.abs_to_path.
              'path': str(self.m.path['start_dir'].join('path', 'to', p)),
              'remote': 'https://fuchsia.googlesource.com/' + p,
              'revision': 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127',
              'current_branch': '',
              'branches': ['(HEAD detached at c22471f)']
          } for p in projects
      ]

    return self(*cmd, step_test_data=lambda: self.test_api.project(test_data))

  def update(self,
             gc=False,
             rebase_tracked=False,
             local_manifest=False,
             run_hooks=True,
             snapshot=None,
             attempts=3,
             **kwargs):
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

  def import_manifest(self,
                      manifest,
                      remote,
                      name=None,
                      revision=None,
                      overwrite=False,
                      **kwargs):
    """Imports manifest into Jiri project.

    Args:
      manifest (str): A file within the repository to use.
      remote (str): A remote manifest repository address.
      name (str): The name of the remote manifest project.
      revision (str): A revision to checkout for the remote.

    Returns:
      A step result.
    """
    cmd = ['import']
    if name:
      cmd.extend(['-name', name])
    if revision:
      cmd.extend(['-revision', revision])
    if overwrite:
      cmd.extend(['-overwrite=true'])
    cmd.extend([manifest, remote])

    return self(*cmd, **kwargs)

  def edit_manifest(self,
                    manifest,
                    projects=None,
                    imports=None,
                    test_data=None,
                    **kwargs):
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
        '-json-output',
        self.m.json.output(),
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

    step = self(
        *cmd,
        step_test_data=lambda: self.m.json.test_api.output(test_data),
        **kwargs)
    return step.json.output

  def patch(self,
            ref,
            host=None,
            project=None,
            delete=False,
            force=False,
            rebase=False,
            cherrypick=False):
    cmd = ['patch']
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
    if cherrypick:  # pragma: no cover
      cmd.extend(['-cherry-pick=true'])
    cmd.extend([ref])

    return self(*cmd)

  def snapshot(self, file=None, test_data=None, **kwargs):
    cmd = [
        'snapshot',
        self.m.raw_io.output(name='snapshot', leak_to=file),
    ]
    if test_data is None:
      test_data = self.test_api.example_snapshot
    step = self(
        *cmd,
        step_test_data=lambda: self.test_api.snapshot(test_data),
        **kwargs)
    return step.raw_io.output

  def source_manifest(self, file=None, test_data=None, **kwargs):
    """Generates a source manifest JSON file.

    Args:
      file (Path): Optional output path for the source manifest.

    Returns:
      The contents of the source manifest as a Python dictionary.
    """
    cmd = [
        'source-manifest',
        self.m.json.output(name='source manifest', leak_to=file),
    ]
    if test_data is None:
      test_data = self.test_api.example_source_manifest
    step = self(
        *cmd,
        step_test_data=lambda: self.test_api.source_manifest(test_data),
        **kwargs)
    return step.json.output

  def emit_source_manifest(self):
    """Emits a source manifest for this build for the current jiri checkout."""
    manifest = self.source_manifest()
    self.m.source_manifest.set_json_manifest('checkout', manifest)

  # TODO(IN-617) Once all api.jiri.checkout() instances have been moved over to
  # using build_input, remove `remote` and `patch_*` arguments.
  def checkout(self,
               manifest,
               remote,
               project=None,
               build_input=None,
               revision=None,
               patch_ref=None,
               patch_gerrit_url=None,
               patch_project=None,
               timeout_secs=None,
               run_hooks=True):
    """Initializes and populates a jiri checkout from a remote manifest.

    Emits a source manifest for the build.

    Args:
      manifest (str): Relative path to the manifest in the remote repository.
      remote (str): URL to the remote repository.
      project (str): The name that jiri should assign to the project.
      build_input (buildbucket.build_pb2.Build.Input): The input to a buildbucket
        build.
      revision (str): A revision to checkout for the remote.
      patch_ref (str): The ref at which a patch lives.
      patch_gerrit_url (str): The Gerrit URL for the patch to apply.
      patch_project (str): The Gerrit project where the patch lives.
      timeout_secs (int): A timeout for jiri update in seconds.
      run_hooks (bool): Whether or not to run the hooks.
    """
    self.init()

    if build_input:
      # Proto messages like build_input cannot have None members.
      gitiles_commit = build_input.gitiles_commit
      revision = revision or gitiles_commit.id

      if build_input.gerrit_changes:
        assert len(build_input.gerrit_changes) == 1
        cl = build_input.gerrit_changes[0]
        revision = revision or 'HEAD'
        patch_project = patch_project or cl.project
        patch_gerrit_url = patch_gerrit_url or 'https://%s' % cl.host
        patch_ref = patch_ref or self.m.gerrit.get_change_ref(
          cl.change, cl.patchset)

    self.import_manifest(manifest, remote, name=project, revision=revision)
    # Note that timeout is not a jiri commandline argument, but a param
    # that will get passed to self.m.step() via kwargs.
    self.update(run_hooks=False, timeout=timeout_secs)
    if patch_ref:
      self.patch(
          patch_ref, host=patch_gerrit_url, project=patch_project, rebase=True)
      self.update(
          gc=True,
          rebase_tracked=True,
          local_manifest=True,
          run_hooks=False,
          timeout=timeout_secs)
    if run_hooks:
      self.run_hooks(local_manifest=patch_ref is not None)
    self.emit_source_manifest()

  def checkout_snapshot(self, snapshot, timeout_secs=None):
    """Initializes and populates a jiri checkout from a snapshot.

    Emits a source manifest for the build.

    Args:
      snapshot (Path): Path to the jiri snapshot.
      timeout_secs (int): A timeout for jiri update in seconds.
    """
    self.init()
    # Hooks must be run during update for a snapshot, otherwise it will be
    # impossible to run them later. It's impossible because jiri doesn't record
    # the hooks anywhere when it updates from a snapshot, so the only way to
    # run hooks inside of the snapshot is to re-run update, which is redundant.
    self.update(run_hooks=True, snapshot=snapshot, timeout=timeout_secs)
    self.m.source_manifest.set_json_manifest('checkout', self.source_manifest())

  def read_manifest_element(self, manifest, element_type, element_name):
    """Reads information about a <project> or <import> from a manifest file.

    Args:
      manifest (str|Path): Path to the manifest file.
      element_type (str): One of 'import' or 'project'.
      element_name (str): The name of the element.

    Returns:
      A dict containing the project fields.  Any fields that are missing or have
      empty values are omitted from the dict.  Examples:

          # Read remote attribute of the returned project
          print(project['remote']) # https://fuchsia.googlesource.com/my_project

          # Check whether remote attribute was present and non-empty.
          if 'remote' in project:
              ...
    """
    if element_type == 'project':
      # This is a Go template matching the schema in pkg/text/template. See docs
      # for `__manifest` for more details.  We format the template as JSON to
      # make it easy to parse into a dict.  The template contains the fields in
      # a manifest <project>.  See //jiri/project/manifest.go for the original
      # definition.  Add fields to this template as-needed.
      template = '''
      {
        "gerrithost": "{{.GerritHost}}",
        "githooks": "{{.GitHooks}}",
        "historydepth": "{{.HistoryDepth}}",
        "name": "{{.Name}}",
        "path": "{{.Path}}",
        "remote": "{{.Remote}}",
        "remotebranch": "{{.RemoteBranch}}",
        "revision": "{{.Revision}}"
      }
      '''
    else:
      assert element_type == 'import'
      # This template contains the fields in a manifest <import>. See
      # //jiri/project/manifest.go for the original definition.
      template = '''
      {
        "manifest": "{{.Manifest}}",
        "name": "{{.Name}}",
        "remote": "{{.Remote}}",
        "revision": "{{.Revision}}",
        "remotebranch": "{{.RemoteBranch}}",
        "root": "{{.Root}}"
      }
      '''
    # Parse the result as JSON
    with self.m.step.nest('read_manifest_' + element_name):
      element_json = self.__manifest(
          manifest=manifest,
          element_name=element_name,
          template=template,
          stdout=self.m.json.output(),
      ).stdout

    # Strip whitespace from any attribute values.  Discard empty values.
    return {k: v.strip() for k, v in element_json.iteritems() if v.strip()}

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
    return self('manifest', '-element', element_name, '-template', template,
                manifest, **kwargs)
