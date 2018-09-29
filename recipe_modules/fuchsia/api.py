# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import collections
import os
import pipes

# Host architecture -> number of bits -> host platform name.
# Add to this dictionary as we support building on more devices.
HOST_PLATFORMS = {
    'intel': {
        64: 'x64',
    },
}

# List of available targets.
TARGETS = ['x64', 'arm64']

# The kernel image.
TARGET_TO_KERNEL_IMAGE = dict(zip(
    TARGETS,
    ['zircon.bin', 'qemu-zircon.bin'],
)) # yapf: disable

# List of available build types.
BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

# The FVM block name.
FVM_BLOCK_NAME = 'fvm.blk'

# The GUID string for the system partition.
# Defined in //zircon/system/public/zircon/hw/gpt.h
GUID_SYSTEM_STRING = '606B000B-B7C7-4653-A7D5-B737332C899D'

# The PCI address to use for the block device to contain test results.
TEST_FS_PCI_ADDR = '06.0'

# How long to wait (in seconds) before killing the test swarming task if there's
# no output being produced.
TEST_IO_TIMEOUT_SECS = 60

# The path in the BootFS manifest that we want runcmds to show up at.
RUNCMDS_BOOTFS_PATH = 'infra/runcmds'

# (variant_name, switch) mapping Fuchsia GN variant names (as used in the
# variant property) to build-zircon.sh switches.
VARIANTS_ZIRCON = [
    ('host_asan', '-H'),
    # TODO(ZX-2197): Don't build Zircon with ASan when building Fuchsia
    # with ASan due to linking problems.  Long run, unclear whether we
    # want to enable ASan in Zircon pieces on Fuchsia ASan bots.
    #('asan', '-A'),
]


class FuchsiaCheckoutResults(object):
  """Represents a Fuchsia source checkout."""

  def __init__(self, root_dir, snapshot_file):
    self._root_dir = root_dir
    self._snapshot_file = snapshot_file

  @property
  def root_dir(self):
    """The path to the root directory of the jiri checkout."""
    return self._root_dir

  @property
  def snapshot_file(self):
    """The path to the jiri snapshot file."""
    return self._snapshot_file


class FuchsiaBuildResults(object):
  """Represents a completed build of Fuchsia."""

  def __init__(self, target, zircon_build_dir, fuchsia_build_dir):
    assert target in TARGETS
    self._zircon_build_dir = zircon_build_dir
    self._fuchsia_build_dir = fuchsia_build_dir
    self._target = target

  @property
  def target(self):
    """The build target for this build."""
    return self._target

  @property
  def zircon_build_dir(self):
    """The directory where Zircon build artifacts may be found."""
    return self._zircon_build_dir

  @property
  def zircon_kernel_image(self):
    """The Zircon kernel image file name."""
    return TARGET_TO_KERNEL_IMAGE[self._target]

  @property
  def fuchsia_build_dir(self):
    """The directory where Fuchsia build artifacts may be found."""
    return self._fuchsia_build_dir

  @property
  def ids(self):
    return self._fuchsia_build_dir.join('ids.txt')


class FuchsiaApi(recipe_api.RecipeApi):
  """APIs for checking out, building, and testing Fuchsia."""

  class FuchsiaTestResults(object):
    """Represents the result of testing of a Fuchsia build."""

    # Constants representing the result of running a test. These enumerate the
    # values of the 'results' field of the entries in the summary.json file
    # obtained from the target device.
    _TEST_RESULT_PASS = 'PASS'
    _TEST_RESULT_FAIL = 'FAIL'

    def __init__(self, name, build_dir, results_dir, zircon_kernel_log,
                 outputs, json_api):
      self._name = name
      self._build_dir = build_dir
      self._results_dir = results_dir
      self._zircon_kernel_log = zircon_kernel_log
      self._outputs = outputs

      # Default to empty values if the summary file is missing.
      if 'summary.json' not in outputs:
        self._raw_summary = ''
        self._summary = {}
      else:
        # Cache the summary file if present.
        self._raw_summary = outputs['summary.json']
        # TODO(kjharland): Raise explicit step failure when parsing fails so
        # that it's clear that the summary file is malformed.
        self._summary = json_api.loads(outputs['summary.json'])

    @property
    def name(self):
      """The unique name for this set of test results."""
      return self._name

    @property
    def build_dir(self):
      """A path to the build directory for symbolization artifacts."""
      return self._build_dir

    @property
    def results_dir(self):
      """A path to the directory that contains test results."""
      return self._results_dir

    @property
    def outputs(self):
      """A dict that maps test outputs to their contents.

      The output paths are relative paths to files containing stdout+stderr data
      and the values are strings containing those contents.
      """
      return self._outputs

    @property
    def raw_summary(self):
      """The raw contents of the JSON summary file or "" if missing."""
      return self._raw_summary

    @property
    def summary(self):
      """The parsed summary file as a Dict or {} if missing."""
      return self._summary

    @property
    def passed_test_outputs(self):
      """All entries in |self.outputs| for tests that passed."""
      return self._filter_outputs_by_test_result(self._TEST_RESULT_PASS)

    @property
    def failed_test_outputs(self):
      """All entries in |self.outputs| for tests that failed."""
      return self._filter_outputs_by_test_result(self._TEST_RESULT_FAIL)

    def _filter_outputs_by_test_result(self, result):
      """Returns all entries in |self.outputs| whose result is |result|.

      Args:
        result (String): one of the _TEST_RESULT_* constants from this class.

      Returns:
        A dict whose keys are paths to the files containing each test's
        stderr+stdout data and whose values are strings containing those
        contents.
      """
      matches = collections.OrderedDict()

      # TODO(kjharland): Sort test names first.
      for test in self.summary['tests']:
        if test['result'] == result:
          # By convention we use the full path to the test binary as the 'name'
          # field in the summary.  The 'output_file' field is a path to the file
          # containing the stderr+stdout data for the test, and we inline the
          # contents of that file as the value in the returned dict.
          matches[test['name']] = self.outputs[test['output_file']]

      return matches

  def __init__(self, fuchsia_properties, *args, **kwargs):
    super(FuchsiaApi, self).__init__(*args, **kwargs)
    self._build_metrics_gcs_bucket = fuchsia_properties.get(
        'build_metrics_gcs_bucket')
    self._test_coverage_gcs_bucket = fuchsia_properties.get(
        'test_coverage_gcs_bucket')

  def checkout(self,
               manifest,
               remote,
               project=None,
               build_input=None,
               revision=None,
               patch_ref=None,
               patch_gerrit_url=None,
               patch_project=None,
               snapshot_gcs_buckets=(),
               timeout_secs=20 * 60):
    """Uses Jiri to check out a Fuchsia project.

    The patch_* arguments must all be set, or none at all.
    The root of the checkout is returned via FuchsiaCheckoutResults.root_dir.

    Args:
      manifest (str): A path to the manifest in the remote (e.g. manifest/minimal)
      remote (str): A URL to the remote repository which Jiri will be pointed at
      project (str): The name of the project
      build_input (buildbucket.build_pb2.Build.Input): The input to a buildbucket
        build.
      revision (str): The revision of the remote repository to import
      patch_ref (str): A reference ID to the patch in Gerrit to apply
      patch_gerrit_url (str): A URL of the patch in Gerrit to apply
      patch_project (str): The name of Gerrit project
      snapshot_gcs_buckets (seq of str): The GCS buckets to upload the Jiri
          snapshot to. None/empty elements are ignored.
      timeout_secs (int): How long to wait for the checkout to complete
          before failing

    Returns:
      A FuchsiaCheckoutResults containing details of the checkout.
    """
    with self.m.context(infra_steps=True):
      self.m.jiri.ensure_jiri()
      self.m.jiri.checkout(
          manifest,
          remote,
          project=project,
          build_input=build_input,
          revision=revision,
          patch_ref=patch_ref,
          patch_gerrit_url=patch_gerrit_url,
          patch_project=patch_project,
          timeout_secs=timeout_secs,
      )

      snapshot_file = self.m.path['cleanup'].join('jiri.snapshot')
      self.m.jiri.snapshot(snapshot_file)
      return self._finalize_checkout(
          snapshot_file=snapshot_file,
          snapshot_gcs_buckets=snapshot_gcs_buckets)

  def checkout_snapshot(self,
                        repository=None,
                        revision=None,
                        gitiles_commit=None,
                        timeout_secs=20 * 60):
    """Uses Jiri to check out Fuchsia from a Jiri snapshot.

    The root of the checkout is returned via FuchsiaCheckoutResults.root_dir.

    Args:
      repository (str): A URL to the remote repository containing the snapshot.
        The snapshot should be available at the top-level in a file called
        'snapshot'.
      revision (str): The git revision to check out from the repository.
      gitiles_commit (buildbucket.common_pb2.GitilesCommit): A Gitiles commit.
      timeout_secs (int): How long to wait for the checkout to complete
          before failing.

    Returns:
      A FuchsiaCheckoutResults containing details of the checkout.
    """
    if gitiles_commit:
      repository = repository or 'https://%s/%s' % (
          gitiles_commit.host,
          gitiles_commit.project,
      )
      revision = revision or gitiles_commit.id

    with self.m.context(infra_steps=True):
      snapshot_repo_dir = self.m.path['cleanup'].join('snapshot_repo')

      # Without any patch information, we just want to fetch whatever we're
      # told via repository and revision.
      self.m.git.checkout(
          url=repository,
          ref=revision,
          path=snapshot_repo_dir,
      )

      return self._checkout_snapshot(snapshot_repo_dir=snapshot_repo_dir)

  def checkout_patched_snapshot(self,
                                gerrit_change=None,
                                patch_gerrit_url=None,
                                patch_issue=None,
                                patch_project=None,
                                patch_ref=None,
                                patch_repository_url=None,
                                timeout_secs=20 * 60):
    """Uses Jiri to check out Fuchsia from a Jiri snapshot from a Gerrit patch.
    The root of the checkout is returned via FuchsiaCheckoutResults.root_dir.

    Args:
      gerrit_change (buildbucket.common_pb2.GerritChange): A Gerrit change.
      patch_gerrit_url (str): A URL of the patch in Gerrit to apply.
      patch_issue (str): The issue number for Gerrit CL.
      patch_project (str): The name of Gerrit project.
      patch_ref (str): A reference ID to the patch in Gerrit to apply.
      patch_repository_url (str): The repository the change is for.
      timeout_secs (int): How long to wait for the checkout to complete
          before failing

    Returns:
      A FuchsiaCheckoutResults containing details of the checkout.
    """
    if gerrit_change:
      patch_gerrit_url = patch_gerrit_url or 'https://%s' % gerrit_change.host
      patch_issue = patch_issue or gerrit_change.change
      patch_project = patch_project or gerrit_change.project

      git_host = gerrit_change.host
      gs_suffix = '-review.googlesource.com'
      assert git_host.endswith(gs_suffix)
      git_host = '%s.googlesource.com' % git_host[:-len(gs_suffix)]
      patch_repository_url = patch_repository_url or 'https://%s/%s' % (
          git_host, gerrit_change.project)

    with self.m.context(infra_steps=True):
      snapshot_repo_dir = self.m.path['cleanup'].join('snapshot_repo')

      # 1) Check out the patch from Gerrit (initializing the repo also).
      # 2) Learn the destination branch for the Gerrit change.
      # 3) Fetch and rebase the patch against the destination branch.
      #
      # Firstly, we want to rebase on top of the upstream branch because when
      # we're testing, we want to test the rebased change to make the tryjob as
      # accurate as possible before submitting.
      #
      # Secondly, we need to fetch the destination branch for a Gerrit change
      # via the Gerrit recipe module because CQ does not provide this
      # information. This is the canonical way in which other Chrome Infra
      # tryjob recipes are able to rebase onto the destination branch.
      self.m.gerrit.ensure_gerrit()
      details = self.m.gerrit.change_details(
          name='get change details',
          change_id='%s~%s' % (patch_project, patch_issue),
          gerrit_host=patch_gerrit_url,
          query_params=["CURRENT_REVISION"],
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

      if not patch_ref:
        current_revision = details['current_revision']
        patch_ref = details['revisions'][current_revision]['ref']

      self.m.git.checkout(
          url='%s/%s' % (patch_gerrit_url, patch_project),
          ref=patch_ref,
          path=snapshot_repo_dir,
      )

      with self.m.context(cwd=snapshot_repo_dir):
        self.m.git('fetch', patch_repository_url, details['branch'])
        self.m.git('rebase', 'FETCH_HEAD')

      return self._checkout_snapshot(snapshot_repo_dir=snapshot_repo_dir)

  def _checkout_snapshot(self, snapshot_repo_dir):
    # Read the snapshot so it shows up in the step presentation.
    snapshot_file = snapshot_repo_dir.join('snapshot')
    cherrypick_file = snapshot_repo_dir.join('cherrypick.json')

    # Perform a jiri checkout from the snapshot.
    self.m.jiri.ensure_jiri()
    self.m.jiri.checkout_snapshot(snapshot_file)

    # Perform cherrypicks if there is a cherrypick file.
    if self.m.path.exists(cherrypick_file):
      # Get the cherrypick json
      cherrypick_json = self.m.file.read_raw(
          'read cherrypick file', cherrypick_file, '{\"topaz\":[\"test\"]}')
      cherrypick_dict = self.m.json.loads(cherrypick_json)

      for project, cherrypicks in cherrypick_dict.items():
        # Get the project relative checkout path and join it to the start_dir.
        # path always exists in the snapshot file, so we don't need to check for its existance.
        project_path = self.m.path['start_dir'].join(
            self.m.jiri.read_manifest_element(
                manifest=snapshot_file,
                element_type='project',
                element_name=project)['path'])

        for cherrypick in cherrypicks:
          self.m.git('-C', project_path, 'cherry-pick', cherrypick,
                     '--keep-redundant-commits')

    return self._finalize_checkout(
        snapshot_file=snapshot_file,
        # This method should never upload a snapshot because the point is that
        # we obtain a checkout from an existing snapshot. The snapshot is
        # already readily available in the repository from whence it was
        # retrieved. Note also that the checkout will never be patched by this
        # method, unlike checkout(). This is because the purpose of the
        # patch_* arguments is to patch the snapshot itself (e.g. to CQ a
        # snapshot update).
        snapshot_gcs_buckets=(),
    )

  def _finalize_checkout(self, snapshot_file, snapshot_gcs_buckets):
    """Finalizes a Fuchsia checkout.

    Constructs a FuchsiaCheckoutResults to return and optionally uploads the
    Jiri snapshot of the Fuchsia checkout to the given GCS buckets.
    """
    snapshot_contents = self.m.file.read_text('read snapshot', snapshot_file)
    # Always log snapshot contents (even if uploading to GCS) to help debug
    # things like tryjob failures during roller-commits.
    snapshot_step_logs = self.m.step.active_result.presentation.logs
    snapshot_step_logs['snapshot_contents'] = snapshot_contents.split('\n')

    # Upload the snapshot to all specified GCS buckets.
    # Don't accidentally iterate over each character in a string.
    assert not isinstance(snapshot_gcs_buckets, basestring)
    # Ignore None/empty elements.
    snapshot_gcs_buckets = [b for b in snapshot_gcs_buckets if b]
    if snapshot_gcs_buckets:
      self.m.gsutil.ensure_gsutil()
      for bucket in snapshot_gcs_buckets:
        self._upload_file_to_gcs(snapshot_file, bucket)

    # TODO(dbort): Add some or all of the jiri.checkout() params if they
    # become useful.
    return FuchsiaCheckoutResults(
        root_dir=self.m.path['start_dir'], snapshot_file=snapshot_file)

  def _build_zircon(self, target, variants, zircon_args):
    """Builds zircon for the specified target."""
    cmd = [
        self.m.path['start_dir'].join('scripts', 'build-zircon.sh'),
        '-v', # level one verbosity
        '-t',
        target,
    ]
    for variant, switch in VARIANTS_ZIRCON:
      if variant in variants:
        cmd.append(switch)
    cmd += [
        '-j',
        self.m.goma.jobs,
        'GOMACC=%s' % self.m.goma.goma_dir.join('gomacc'),
    ]
    if zircon_args:
      cmd.append(' '.join(zircon_arg for zircon_arg in zircon_args))
    self.m.step('zircon', cmd)

  def _build_fuchsia(self, build, build_type, packages, variants, gn_args,
                     ninja_targets, boards, products):
    """Builds fuchsia given a FuchsiaBuildResults and other GN options."""
    with self.m.step.nest('build fuchsia'):
      args = [
          'target_cpu="%s"' % build.target,
          'use_goma=true',
          'goma_dir="%s"' % self.m.goma.goma_dir,
          'is_debug=%s' % ('true' if build_type == 'debug' else 'false'),
      ]

      if boards:
        args.append(' '.join('import("//%s")' % board for board in boards))

      if packages:
        fuchsia_packages_format = 'fuchsia_packages=[%s]'
        # if boards is set, append to fuchsia_packages.
        # boards set fuchsia_packages, we don't want to overwrite.
        if boards:
          fuchsia_packages_format = 'fuchsia_packages+=[%s]'

        args.append(fuchsia_packages_format % ','.join(
            '"%s"' % pkg for pkg in packages))

      if products:
        args.append('fuchsia_products=[%s]' % ','.join(
            '"%s"' % product for product in products))

      args += {
          'lto': [
              'use_lto=true',
              'use_thinlto=false',
          ],
          'thinlto': [
              'use_lto=true',
              'use_thinlto=true',
              'thinlto_cache_dir="%s"' % self.m.path['cache'].join('thinlto'),
          ],
      }.get(build_type, [])

      if variants:
        args.append(
            'select_variant=[%s]' % ','.join(['"%s"' % v for v in variants]))

      gen_cmd = [
          self.m.path['start_dir'].join('buildtools', 'gn'),
          'gen',
          build.fuchsia_build_dir,
          '--check',
          '--args=%s' % ' '.join(args + list(gn_args)),
      ]

      # Collect gn tracing data if specified.
      if self._build_metrics_gcs_bucket:
        gen_cmd.append('--tracelog=' +
                       str(self.m.path['cleanup'].join('gn_trace.json')))

      self.m.step('gn gen', gen_cmd)

      self.m.step('ninja', [
          self.m.path['start_dir'].join('buildtools', 'ninja'),
          '-C',
          build.fuchsia_build_dir,
          '-j',
          self.m.goma.jobs,
      ] + list(ninja_targets))

    self._tracing_data(build)

  def build(self,
            target,
            build_type,
            packages,
            variants=(),
            gn_args=[],
            ninja_targets=(),
            boards=[],
            products=[],
            zircon_args=[]):
    """Builds Fuchsia from a Jiri checkout.

    Expects a Fuchsia Jiri checkout at api.path['start_dir'].

    Args:
      target (str): The build target, see TARGETS for allowed targets
      build_type (str): One of the build types in BUILD_TYPES
      packages (sequence[str]): A sequence of packages to pass to GN to build
      variants (sequence[str]): A sequence of build variant selectors to pass
        to GN in `select_variant`
      gn_args (sequence[str]): Additional arguments to pass to GN
      ninja_targets (sequence[str]): Additional target args to pass to ninja
      boards (sequence[str]): A sequence of boards to pass to GN to build
      products (sequence[str]): A sequence of products to pass to GN to build

    Returns:
      A FuchsiaBuildResults, representing the recently completed build.
    """
    assert target in TARGETS
    assert build_type in BUILD_TYPES

    if build_type == 'debug':
      build_dir = 'debug'
    else:
      build_dir = 'release'
    out_dir = self.m.path['start_dir'].join('out')
    build = FuchsiaBuildResults(
        target=target,
        zircon_build_dir=out_dir.join('build-zircon', 'build-%s' % target),
        fuchsia_build_dir=out_dir.join('%s-%s' % (build_dir, target)),
    )
    with self.m.step.nest('build'):
      self.m.goma.ensure_goma()
      with self.m.goma.build_with_goma():
        self._build_zircon(target, variants, zircon_args)
        self._build_fuchsia(
            build=build,
            build_type=build_type,
            packages=packages,
            variants=variants,
            gn_args=gn_args,
            ninja_targets=ninja_targets,
            boards=boards,
            products=products)
    self.m.minfs.minfs_path = out_dir.join('build-zircon', 'tools', 'minfs')
    self.m.zbi.zbi_path = out_dir.join('build-zircon', 'tools', 'zbi')

    return build

  def _symbolize_compat(self, build_dir, data):
    """Invokes zircon's symbolization script to symbolize the given data."""
    symbolize_cmd = [
        self.m.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
        '--no-echo',
        '--build-dir',
        build_dir,
    ]
    symbolize_result = self.m.step(
        'symbolize',
        symbolize_cmd,
        stdin=self.m.raw_io.input(data=data),
        stdout=self.m.raw_io.output(),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs[
          'symbolized backtraces'] = symbolized_lines

  def _symbolize_filter(self, build_dir, data, json_output=None):
    """Invokes zircon's symbolization script to symbolize the given data."""
    downloads_dir = self.m.path['start_dir'].join('zircon', 'prebuilt',
                                                  'downloads')
    symbolize_cmd = [
        downloads_dir.join('symbolize'),
        '-ids',
        build_dir.join('ids.txt'),
        '-llvm-symbolizer',
        downloads_dir.join('clang', 'bin', 'llvm-symbolizer'),
    ]
    if json_output:
      symbolize_cmd.extend(['-json-output', json_output])
    symbolize_result = self.m.step(
        'symbolize logs',
        symbolize_cmd,
        stdin=self.m.raw_io.input(data=data),
        stdout=self.m.raw_io.output(),
        step_test_data=
        lambda: self.m.raw_io.test_api.stream_output('blah\nblah\n'))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized logs'] = symbolized_lines
    self.m.step('print file', ['cat', json_output])

  def _symbolize(self, build_dir, data, json_output=None):
    # Do both old and new symbolization styles for now.
    self._symbolize_compat(build_dir, data)
    self._symbolize_filter(build_dir, data, json_output)

  def _isolate_files_at_isolated_root(self, files):
    """Isolates a set of files such that they all appear at the top-level.

    Args:
      files (seq[Path]): A list of paths which point to files to be isolated.

    Returns:
      The isolated hash that may be used to reference and download the
      artifacts.
    """
    assert files

    self.m.isolated.ensure_isolated(version='latest')

    isolated = self.m.isolated.isolated()

    # Add the extra files to isolated at the top-level.
    names = set()
    for path in files:
      # Ensure we don't have duplicate names at the top-level.
      name = self.m.path.basename(path)
      assert name not in names
      names.add(name)
      isolated.add_file(
          path, wd=self.m.path.abs_to_path(self.m.path.dirname(path)))

    # Archive the isolated.
    return isolated.archive('isolate artifacts')

  @property
  def results_dir_on_target(self):
    """The directory on target to which target test results will be written."""
    return '/tmp/infra-test-output'

  @property
  def results_dir_on_host(self):
    """The directory on host to which host and target test results will be written.

    Target test results will be copied over to this location and host test
    results will be written here. Host and target tests on should write to
    separate subdirectories so as not to collide.
    """
    return self.m.path['start_dir'].join('test_results')

  def test_on_host(self, build):
    """Tests a Fuchsia build from the host machine.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    runtests = build.zircon_build_dir.join('tools', 'runtests')
    host_test_dir = build.fuchsia_build_dir.join('host_tests')

    # Write test results to the 'host' subdirectory of |results_dir_on_host|
    # so as not to collide with target test results.
    test_results_dir = self.results_dir_on_host.join('host')

    # The following executes a script that (1) sets sanitizer-related environment
    # variables, given a path to the clang pre-built binaries as its first
    # argument, and then (2) executes the remaining arguments as an appended
    # command.
    host_platform = HOST_PLATFORMS[self.m.platform.arch][self.m.platform.bits]
    set_vars_and_run_cmd = [
        self.m.path['start_dir'].join('build', 'gn_run_binary.sh'),
        self.m.path['start_dir'].join(
            'buildtools', '%s-%s' % (self.m.platform.name, host_platform),
            'clang', 'bin'),
    ]

    # Allow the runtests invocation to fail without resulting in a step failure.
    # The relevant, individual test failures will be reported during the
    # processing of summary.json - and an early step failure will prevent this.
    self.m.step(
        'run host tests',
        set_vars_and_run_cmd + [
            runtests,
            '-o',
            self.m.raw_io.output_dir(leak_to=test_results_dir),
            host_test_dir,
        ],
        ok_ret='any')

    # Extract test results.
    test_results_map = self.m.step.active_result.raw_io.output_dir
    return self.FuchsiaTestResults(
        name='host',
        build_dir=build.fuchsia_build_dir,
        results_dir=test_results_dir,
        zircon_kernel_log=None,  # We did not run tests on target.
        outputs=test_results_map,
        json_api=self.m.json,
    )

  def _create_runcmds_script(self, device_type, test_cmds, output_path):
    """Creates a script for running tests on boot."""
    # The device topological path is the toplogical path to the block device
    # which will contain test output.
    device_topological_path = '/dev/sys/pci/00:%s/virtio-block/block' % (
        TEST_FS_PCI_ADDR)

    # Script that mounts the block device to contain test output and runs tests,
    # dropping test output into the block device.
    results_dir = self.results_dir_on_target
    runcmds = [
        'mkdir %s' % results_dir,
    ]
    if device_type == 'QEMU':
      runcmds.extend([
          # Wait until the MinFS test image shows up (max <timeout> ms).
          'waitfor class=block topo=%s timeout=60000' % device_topological_path,
          'mount %s %s' % (device_topological_path, results_dir),
      ] + test_cmds + [
          'umount %s' % results_dir,
          'dm poweroff',
      ])
    else:
      runcmds.extend(test_cmds)
    self.m.file.write_text('write runcmds', output_path, '\n'.join(runcmds))
    self.m.step.active_result.presentation.logs['runcmds'] = runcmds

  def _construct_qemu_task_request(self, task_name, zbi_path, build, test_pool,
                                   images, timeout_secs, external_network,
                                   secret_bytes):
    """Constructs a Swarming task request which runs Fuchsia tests inside QEMU.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      test_pool (str): Swarming pool from which the test task will be drawn.
      images (dict[string]Path): A map between the canonical name of an
        image produced by the Fuchsia build to the path to that image on the
        local disk.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.
      external_network (bool): Whether to give Fuchsia inside QEMU access
        to the external network.
      secret_bytes (str): secret bytes to pass to the QEMU task.

    Returns:
      An api.swarming.TaskRequest representing the swarming task request.
    """
    self.m.swarming.ensure_swarming(version='latest')

    # Use canonical image names to refer to images to extract the path to that
    # image. These dict keys come from the images.json format which is produced
    # by a Fuchsia build.
    # TODO(BLD-253): Point to the schema once there is one.
    storage_full_path = images['storage-full']
    qemu_kernel_path = images['qemu-kernel']

    # All the *_name references below act as relative paths to the corresponding
    # artifacts in the test Swarming task, since we isolate all of the artifacts
    # into the root directory where the isolate is extracted.
    zbi_name = self.m.path.basename(zbi_path)
    storage_full_name = self.m.path.basename(storage_full_path)
    qemu_kernel_name = self.m.path.basename(qemu_kernel_path)

    # As part of running tests, we'll send a MinFS image over to another machine
    # which will be declared as a block device in QEMU, at which point
    # Fuchsia will mount it and write test output to.
    minfs_image_name = 'output.fs'

    # Create MinFS image (which will hold test output). We choose 1G for the
    # MinFS image arbitrarily, and it appears it can hold our test output
    # comfortably without going overboard on size.
    minfs_image_path = self.m.path['start_dir'].join(minfs_image_name)
    self.m.minfs.create(minfs_image_path, '1G', name='create test image')

    botanist_cmd = [
      './botanist/botanist',
      'qemu',
      '-qemu-dir', './qemu/bin',
      '-qemu-kernel', qemu_kernel_name,
      '-zircon-a', zbi_name,
      '-storage-full', storage_full_name,
      '-arch', build.target,
      '-minfs', minfs_image_name,
      '-pci-addr', TEST_FS_PCI_ADDR,
      '-use-kvm'
    ] # yapf: disable

    if external_network:
      botanist_cmd.append('-enable-networking')

    botanist_cmd.append(
        'zircon.autorun.system=/boot/bin/sh+/boot/%s' % RUNCMDS_BOOTFS_PATH)

    # Isolate the Fuchsia build artifacts in addition to the test image and the
    # qemu runner.
    isolated_hash = self._isolate_files_at_isolated_root([
        zbi_path,
        storage_full_path,
        qemu_kernel_path,
        minfs_image_path,
    ])

    cipd_arch = {
        'arm64': 'arm64',
        'x64': 'amd64',
    }[build.target]

    dimension_cpu = {
        'arm64': 'arm64',
        'x64': 'x86-64',
    }[build.target]

    return self.m.swarming.task_request(
        name=task_name,
        cmd=botanist_cmd,
        isolated=isolated_hash,
        dimensions={
            'pool': test_pool,
            'os': 'Debian',
            'cpu': dimension_cpu,
            'kvm': '1',
        },
        io_timeout_secs=TEST_IO_TIMEOUT_SECS,
        hard_timeout_secs=timeout_secs,
        secret_bytes=secret_bytes,
        outputs=[minfs_image_name],
        cipd_packages=[
            ('qemu', 'fuchsia/qemu/linux-%s' % cipd_arch, 'latest'),
            ('botanist', 'fuchsia/infra/botanist/linux-%s' % cipd_arch,
             'latest'),
        ],
    )

  def _construct_device_task_request(self, task_name, device_type, zbi_path,
                                     build, test_pool, images, pave,
                                     timeout_secs):
    """Constructs a Swarming task request to run Fuchsia tests on a device.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      test_pool (str): Swarming pool from which the test task will be drawn.
      images (dict[string]Path): A map between the canonical name of an
        image produced by the Fuchsia build to the path to that image on the
        local disk.
      pave (bool): Whether or not the build artifacts should be paved.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.

    Returns:
      An api.swarming.TaskRequest representing the swarming task request.
    """
    # TODO(BLD-253): images in doc string should point to the schema once there is one.

    self.m.swarming.ensure_swarming(version='latest')

    # All the *_name references below act as relative paths to the corresponding
    # artifacts in the test Swarming task, since we isolate all of the artifacts
    # into the root directory where the isolate is extracted.
    zbi_name = self.m.path.basename(zbi_path)

    # Construct the botanist command.
    output_archive_name = 'out.tar'
    botanist_cmd = [
      './botanist/botanist',
      'zedboot',
      '-properties', '/etc/botanist/config.json',
      '-kernel', zbi_name,
      '-results-dir', self.results_dir_on_target,
      '-out', output_archive_name,
    ] # yapf: disable

    # image_paths collects the paths to all artifacts consumed by bonanist.
    # Paving builds will add additional paths.
    image_paths = [
        zbi_path,
    ]

    # If we're paving, ensure we add the additional necessary artifacts.
    if pave:
      efi_path = images['efi']
      efi_name = self.m.path.basename(efi_path)

      storage_sparse_path = images['storage-sparse']
      storage_sparse_name = self.m.path.basename(storage_sparse_path)

      image_paths.extend([
          efi_path,
          storage_sparse_path,
      ])
      botanist_cmd.extend([
          '-efi',
          efi_name,
          '-fvm',
          storage_sparse_name,
      ])

      data_template_path = images.get('data-template', None)
      if data_template_path:
        data_template_name = self.m.path.basename(data_template_path)

        image_paths.extend([data_template_path])
        botanist_cmd.extend([
            '-fvm',
            data_template_name,
        ])

    # Add the kernel command line arg for invoking runcmds.
    botanist_cmd.append(
        'zircon.autorun.system=/boot/bin/sh+/boot/%s' % RUNCMDS_BOOTFS_PATH)

    # Isolate all the necessary artifacts used by the botanist command.
    isolated_hash = self._isolate_files_at_isolated_root(image_paths)

    return self.m.swarming.task_request(
        name=task_name,
        cmd=botanist_cmd,
        isolated=isolated_hash,
        dimensions={
            'pool': test_pool,
            'device_type': device_type,
        },
        io_timeout_secs=TEST_IO_TIMEOUT_SECS,
        hard_timeout_secs=timeout_secs,
        outputs=[output_archive_name],
        cipd_packages=[('botanist', 'fuchsia/infra/botanist/linux-amd64',
                        'latest')],
    )

  def _extract_test_results(self, device_type, archive_path, shard_name='', leak_to=None):
    """Extracts test results from an archive.

    The format of the archive depends on device_type, so that is used to
    determine the method we use to extract test results.

    Args:
      device_type (str): The type of device tests were run on.
      archive_path (Path): The path to the archive which contains test results.
      leak_to (Path): Optionally leak the contents of the archive to a
        directory.
      shard_name (str): The optional name of the shard for which we're
        extracting test results. This will be included in the step name for
        testing purposes.

    Returns:
      A dict mapping a filepath relative to the root of the archive to the
      contents of that file in the archive.
    """
    step_name = 'extract results'
    if shard_name:
      step_name = 'extract %s results' % shard_name
    if device_type == 'QEMU':
      return self.m.minfs.copy_image(
          step_name=step_name,
          image_path=archive_path,
          out_dir=leak_to,
      ).raw_io.output_dir
    else:
      self.m.tar.ensure_tar()
      return self.m.tar.extract(
          step_name=step_name,
          path=archive_path,
          directory=self.m.raw_io.output_dir(leak_to=leak_to),
      ).raw_io.output_dir

  def _image_paths(self, build):
    """Produces a mapping of image name to Path in the build.

    Args:
      build (FuchsiaBuildResults): The build for which we want to get image
        paths from.

    Returns:
      A dict mapping a canonical name for the image to its Path in the build
        directory.
    """
    raw_images = self.m.json.read(
        'read image manifest',
        build.fuchsia_build_dir.join('images.json'),
    ).json.output

    return {
        image['name']: self.m.path.abs_to_path(
            self.m.path.realpath(build.fuchsia_build_dir.join(image['path'])))
        for image in raw_images
    }

  def _decrypt_secrets(self, build):
    """Decrypts the secrets included in the build.

    Args:
      build (FuchsiaBuildResults): The build for which secret specs were
        generated.

    Returns:
      The dictionary that maps secret spec name to the corresponding plaintext.
    """
    self.m.cloudkms.ensure_cloudkms()

    secret_spec_dir = build.fuchsia_build_dir.join('secret_specs')
    secrets_map = {}
    with self.m.step.nest('process secret specs'):
      secret_spec_files = self.m.file.listdir('list', secret_spec_dir)
      for secret_spec_file in secret_spec_files:
        basename = self.m.path.basename(secret_spec_file)
        # Skip the 'ciphertext' subdirectory.
        if basename == 'ciphertext':
          continue

        secret_name, _ = basename.split('.json', 1)
        secret_spec = self.m.json.read('read spec for %s' % secret_name,
                                       secret_spec_file).json.output

        # For each test spec file <name>.json in this directory, there is an
        # associated ciphertext file at ciphertext/<name>.ciphertext.
        ciphertext_file = secret_spec_dir.join('ciphertext',
                                               '%s.ciphertext' % secret_name)

        key_path = secret_spec['cloudkms_key_path']
        secrets_map[secret_name] = self.m.cloudkms.decrypt(
            'decrypt secret for %s' % secret_name, key_path, ciphertext_file,
            self.m.raw_io.output()).raw_io.output
    return secrets_map

  def test(self,
           build,
           test_pool,
           test_cmds,
           device_type,
           timeout_secs=40 * 60,
           pave=True,
           external_network=False,
           requires_secrets=False):
    """Tests a Fuchsia build on the specified device.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      test_pool (str): Swarming pool from which the test task will be drawn.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.
      external_network (bool): Whether to enable access to the external
        network when executing tests. Ignored if device_type != 'QEMU'.
      requires_secrets (bool): Whether tests require plaintext secrets;
        ignored if device_type == 'QEMU'.
      pave (bool): Whether to pave the image to disk. Ignored if
        device_type == 'QEMU'.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    assert bool(test_cmds)
    assert bool(device_type)

    runcmds_path = self.m.path['cleanup'].join('runcmds')
    self._create_runcmds_script(device_type, test_cmds, runcmds_path)

    images = self._image_paths(build)

    # Inject the runcmds script into the bootfs image.
    if not pave and device_type != 'QEMU':
      zbi_path = images['netboot']
    else:
      zbi_path = images['zircon-a']
    new_zbi_path = build.fuchsia_build_dir.join('test-infra.zbi')
    self.m.zbi.copy_and_extend(
        step_name='create test zbi',
        input_image=zbi_path,
        output_image=new_zbi_path,
        manifest={RUNCMDS_BOOTFS_PATH: runcmds_path},
    )

    if device_type == 'QEMU':
      secret_bytes = ''
      if requires_secrets:
        secret_bytes = self.m.json.dumps(self._decrypt_secrets(build))
      task = self._construct_qemu_task_request(
          task_name='all tests',
          zbi_path=new_zbi_path,
          build=build,
          test_pool=test_pool,
          images=images,
          timeout_secs=timeout_secs,
          external_network=external_network,
          secret_bytes=secret_bytes,
      )
    else:
      task = self._construct_device_task_request(
          task_name='all tests',
          device_type=device_type,
          zbi_path=new_zbi_path,
          build=build,
          test_pool=test_pool,
          images=images,
          pave=pave,
          timeout_secs=timeout_secs,
      )

    with self.m.context(infra_steps=True):
      # Spawn task.
      requests_json = self.m.swarming.spawn_tasks(tasks=[task])

      # Run and upload bloaty data (will run only if specified). Note that
      # we run this before calling collect so that run_bloaty runs in parallel
      # with tests to speed up overall execution a little bit.
      self.run_bloaty(build)

      # Collect results.
      results = self.m.swarming.collect(
          requests_json=self.m.json.input(requests_json))
      assert len(results) == 1, 'len(%s) != 1' % repr(results)
      result = results[0]
    self.analyze_collect_result('task results', result, build.fuchsia_build_dir)

    with self.m.context(infra_steps=True):
      # result.outputs contains the file outputs produced by the Swarming task,
      # returned via isolate. It's a mapping of the 'name' of the output,
      # represented as its relative path within the isolated it was returned in,
      # to a Path object pointing to its location on the local disk. For each of
      # the above tasks, there should be exactly one output.
      assert len(result.outputs) == 1, 'len(%s) != 1' % repr(result.outputs)
      archive_name = result.outputs.keys()[0]

      test_results_dir = self.results_dir_on_host.join('target', result.id)
      test_results_map = self._extract_test_results(
          device_type=device_type,
          archive_path=result.outputs[archive_name],
          # Write test results to a subdirectory of |results_dir_on_host|
          # so as not to collide with host test results.
          leak_to=test_results_dir,
      )

    return self.FuchsiaTestResults(
        name='all',
        build_dir=build.fuchsia_build_dir,
        results_dir=test_results_dir,
        zircon_kernel_log=result.output,
        outputs=test_results_map,
        json_api=self.m.json,
    )

  # TODO(mknyszek): Rename to test and delete test when this is stable.
  def test_in_shards(self, test_pool, build, timeout_secs=40 * 60):
    """Tests a Fuchsia build by sharding.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      test_pool (str): The Swarming pool to schedule test tasks in.
      build (FuchsiaBuildResults): The Fuchsia build to test.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.

    Returns:
      A list of FuchsiaTestResults representing the completed test tasks.
    """
    images = self._image_paths(build)

    # Run the testsharder to collect test specifications and shard them.
    self.m.testsharder.ensure_testsharder()
    shards = self.m.testsharder.execute(
        'create test shards',
        target_arch=build.target,
        # TODO(IN-647): Write a real platforms file that's part of the Fuchsia
        # source.
        platforms_file=self.m.json.input([
            {'name': 'QEMU', 'arch': '*'},
            {'name': 'Intel NUC Kit NUC6i3SYK', 'arch': 'x64'},
            {'name': 'Intel NUC Kit NUC7i5DNHE', 'arch': 'x64'},
        ]),
        fuchsia_build_dir=build.fuchsia_build_dir,
    )

    # Generate Swarming task requests.
    task_requests = []
    shard_name_to_device_type = {}
    for shard in shards:
      shard_name_to_device_type[shard.name] = shard.device_type

      # Produce runtests file for shard.
      test_locations = []
      for test in shard.tests:
        test_locations.append(test.location)
      runtests_file = self.m.path['cleanup'].join('tests-%s' % shard.name)
      self.m.file.write_text(
          name='write %s test list' % shard.name,
          dest=runtests_file,
          text_data='\n'.join(test_locations) + '\n',
      )

      # Produce runcmds script for shard.
      runtests_file_bootfs_path = 'infra/shard.run'
      runcmds_path = self.m.path['cleanup'].join('runcmds-%s' % shard.name)
      self._create_runcmds_script(
          device_type=shard.device_type,
          test_cmds=[
              'runtests -o %s -f /boot/%s' % (
                  self.results_dir_on_target,
                  runtests_file_bootfs_path,
              )
          ],
          output_path=runcmds_path,
      )

      # Create new zbi image for shard.
      shard_zbi_path = build.fuchsia_build_dir.join('fuchsia-%s.zbi' % shard.name)
      self.m.zbi.copy_and_extend(
        step_name='create zbi for %s' % shard.name,
        # TODO(IN-655): Add support for using the netboot image in non-paving
        # cases.
        input_image=images['zircon-a'],
        output_image=shard_zbi_path,
        manifest={
            RUNCMDS_BOOTFS_PATH: runcmds_path,
            runtests_file_bootfs_path: runtests_file,
        },
      )

      if shard.device_type == 'QEMU':
        task_requests.append(self._construct_qemu_task_request(
            task_name=shard.name,
            zbi_path=shard_zbi_path,
            test_pool=test_pool,
            build=build,
            images=images,
            timeout_secs=timeout_secs,
            # TODO(IN-654): Add support for external_network and secret_bytes.
            external_network=False,
            secret_bytes='',
        ))
      else:
        task_requests.append(self._construct_device_task_request(
            task_name=shard.name,
            test_pool=test_pool,
            device_type=shard.device_type,
            zbi_path=shard_zbi_path,
            build=build,
            images=images,
            timeout_secs=timeout_secs,
            # TODO(IN-655): Add support for non-paving tests.
            pave=True,
        ))

    with self.m.context(infra_steps=True):
      # Spawn tasks.
      requests_json = self.m.swarming.spawn_tasks(tasks=task_requests)

      # Collect results.
      results = self.m.swarming.collect(
          requests_json=self.m.json.input(requests_json))

      # Iterate over all task results, check them, and collect test results.
      fuchsia_test_results = []
      for result in results:
        # Figure out what happened to the swarming tasks.
        self.analyze_collect_result(
            step_name='%s task results' % result.name,
            result=result,
            build_dir=build.fuchsia_build_dir,
        )
        # Extract test results (there should only be one archive).
        assert len(result.outputs) == 1
        archive_name = result.outputs.keys()[0]
        results_dir = self.results_dir_on_host.join(result.id)
        test_results_map = self._extract_test_results(
            shard_name=result.name,
            device_type=shard_name_to_device_type[result.name],
            archive_path=result.outputs[archive_name],
            # Write test results to the a subdirectory of |results_dir_on_host|
            # so as not to collide with host test results.
            leak_to=results_dir,
        )
        fuchsia_test_results.append(self.FuchsiaTestResults(
            name=shard.name,
            build_dir=build.fuchsia_build_dir,
            results_dir=results_dir,
            zircon_kernel_log=result.output,
            outputs=test_results_map,
            json_api=self.m.json,
        ))
    return fuchsia_test_results

  def analyze_collect_result(self, step_name, result, build_dir):
    """Analyzes a swarming.CollectResult and reports results as a step.

    Args:
      step_name (str): The display name of the step for this analysis.
      result (swarming.CollectResult): The swarming collection result to analyze.
      build_dir (Path): A path to the build directory for symbolization artifacts.

    Raises:
      A StepFailure if a kernel panic is detected, or if the tests timed out.
      An InfraFailure if the swarming task failed for a different reason.
    """
    if result.is_infra_failure():
      raise self.m.step.InfraFailure('Failed to collect: %s' % result.output)
    elif result.no_resource():
      raise self.m.step.InfraFailure('Found no bots to run this task')
    elif result.expired():
      raise self.m.step.InfraFailure('Timed out waiting for a bot to run on')

    with self.m.step.nest(step_name) as step_result:
      if result.output:
        # TODO: We should store this path somewhere.
        symbolize_dump = self.m.path['cleanup'].join('symbolize-dump.json')
        # Always symbolize the result output if present.
        self._symbolize(build_dir, result.output, symbolize_dump)
      kernel_output_lines = result.output.split('\n')
      step_result.presentation.logs['kernel log'] = kernel_output_lines
      if result.is_failure():
        if result.timed_out():
          # If we have a timeout with a successful collect, then this must be an
          # io_timeout failure, since task timeout > collect timeout.
          step_result.presentation.step_text = 'i/o timeout'
          step_result.presentation.status = self.m.step.FAILURE
          failure_lines = [
              'I/O timed out, no output for %s seconds.' % TEST_IO_TIMEOUT_SECS,
              'Last 10 lines of kernel output:',
          ] + kernel_output_lines[-10:]
          raise self.m.step.StepFailure('\n'.join(failure_lines))
        # At this point its likely an infra issue with QEMU.
        step_result.presentation.status = self.m.step.EXCEPTION
        raise self.m.step.InfraFailure(
            'Swarming task failed:\n%s' % result.output)
      elif 'KERNEL PANIC' in result.output:
        step_result.presentation.step_text = 'kernel panic'
        step_result.presentation.status = self.m.step.FAILURE
        raise self.m.step.StepFailure(
            'Found kernel panic. See symbolized output for details.')

  def analyze_test_results(self, test_results):
    """Analyzes test results represented by a FuchsiaTestResults.

    Args:
      test_results (FuchsiaTestResults): The test results.

    Raises:
      A StepFailure if any of the discovered tests failed.
    """
    with self.m.step.nest('%s test results' % test_results.name):
      # Log the results of each test.
      self.report_test_results(test_results)

      if self._test_coverage_gcs_bucket:
        symbolize_dump = self.m.path['cleanup'].join('symbolize-dump.json')
        self._process_coverage(test_results, symbolize_dump)

      if test_results.failed_test_outputs:
        # Halt with a step failure.
        raise self.m.step.StepFailure('Test failure(s): ' + ', '.join(
            test_results.failed_test_outputs.keys()))

  def report_test_results(self, test_results):
    """Logs individual test results in separate steps.

    Args:
      test_results (FuchsiaTestResults): The test results.
    """
    if not test_results.summary:
      # Halt with step failure if summary file is missing.
      raise self.m.step.StepFailure(
          'Test summary JSON not found, see kernel log for details')

    # Log the summary file's contents.
    raw_summary_log = test_results.raw_summary.split('\n')
    self.m.step.active_result.presentation.logs[
        'summary.json'] = raw_summary_log

    # Log the contents of each output file mentioned in the summary.
    # Note this assumes the outputs are all plain text.
    for output_name, output_path in test_results.summary.get('outputs',
                                                             {}).iteritems():
      output_str = test_results.outputs[output_path]
      self.m.step.active_result.presentation.logs[output_name] = (
          output_str.split('\n'))

    root_dir = str(self.m.path['start_dir'])
    for test in test_results.summary['tests']:
      test_name = test['name']
      # For host paths, replace the Fuchsia root with '//', the standard
      # shorthand used in GN and documentation.
      if test_name.startswith(root_dir):
        test_name = '//%s' % os.path.relpath(test_name, root_dir)
      test_output = test_results.outputs[test['output_file']]
      # Create individual step just for this test.
      step_result = self.m.step(test_name, None)
      # Always log the result regardless of test outcome.
      step_result.presentation.logs['stdio'] = test_output.split('\n')
      # Report step failure for this test if it did not pass.  This is a hack
      # we must use because we don't yet have a system for test-indexing.
      # TODO(kjharland): Log failing tests first to make it easier see them when
      # scanning the build page (also consider sorting by name).
      if test['result'] != 'PASS':
        step_result.presentation.status = self.m.step.FAILURE

  def _tar_fuchsia_boot_data(self, build_results):
    """Collects build artifacts necessary to boot Fuchsia into a tarball.

    Args:
      build_results (FuchsiaBuildResults): The Fuchsia build results to get
        artifacts from.

    Returns:
      A Path to a tarball containing Fuchsia packages.
    """

    # Begin creating a Fuchsia paving artifacts archive.
    archive = self.m.tar.create(
        self.m.path['cleanup'].join('fuchsia.tar.gz'), compression='gzip')

    # Add the images directory, which contain system images.
    archive.add(
        build_results.fuchsia_build_dir.join('images'),
        build_results.fuchsia_build_dir)

    # Glob for bootdata binaries.
    bootdata_paths = self.m.file.glob_paths(
        name='glob bootdata',
        source=build_results.fuchsia_build_dir,
        pattern='bootdata-blob-*.bin',
        test_data=['/path/to/out/bootdata-blob-pc.bin'],
    )

    # Add all the bootdata-*.bin files, which contain the core ramdisk necessary
    # to boot.
    for p in bootdata_paths:
      archive.add(p, build_results.fuchsia_build_dir)

    # Add SSH keys, making it easier for users to SSH into devices that are
    # paved with buildbot-generated images.
    archive.add(
        build_results.fuchsia_build_dir.join('ssh-keys'),
        build_results.fuchsia_build_dir)

    # Add args.gn, a file containing the arguments passed to GN. This is useful
    # for understanding what packages went into the build, as well as the over
    # build configuration.
    archive.add(
        build_results.fuchsia_build_dir.join('args.gn'),
        build_results.fuchsia_build_dir)

    # Add build artifact manfiest files.  These are shell scripts that are sourced
    # by //scripts/devshell to provide paths to images and other files used for
    # paving.
    archive.add(
        build_results.fuchsia_build_dir.join('image_paths.sh'),
        build_results.fuchsia_build_dir)
    archive.add(
        build_results.fuchsia_build_dir.join('zedboot_image_paths.sh'),
        build_results.fuchsia_build_dir)

    # Add the bootserver tool from zircon. Note that since the CWD is set to the
    # zircon build dir, it will be placed in tools/bootserver in the archive.
    # This makes the packages self-sufficient, allowing one to boot Fuchsia on a
    # device without having to obtain any additional dependencies.
    archive.add(
        build_results.zircon_build_dir.join('tools', 'bootserver'),
        build_results.zircon_build_dir)

    # Add the zircon kernel binary.
    archive.add(
        build_results.zircon_build_dir.join(build_results.zircon_kernel_image),
        build_results.zircon_build_dir)

    # Finalize the archive and upload it.
    archive.tar('tar fuchsia')

    # Return a Path to the tarball.
    return archive.path

  def _tar_fuchsia_packages(self, build_results):
    """Collects Fuchsia packages generated by the build into a tarball.

    Args:
      build_results (FuchsiaBuildResults): The Fuchsia build results to get
        artifacts from.

    Returns:
      A Path to a tarball containing Fuchsia packages.
    """
    # Begin creating Fuchsia packages archive.
    archive = self.m.tar.create(
        self.m.path['cleanup'].join('packages.tar.gz'), compression='gzip')

    # Add targets and blobs under 'targets' and 'blobs'. These directories
    # together make up complete Fuchsia packages which may be pushed into the
    # system.
    amber_repo_dir = build_results.fuchsia_build_dir.join(
        'amber-files', 'repository')
    archive.add(amber_repo_dir.join('targets'), directory=amber_repo_dir)
    archive.add(amber_repo_dir.join('blobs'), directory=amber_repo_dir)

    # Add a host_x64 directory containing the contents of host_x64/amber-publish
    # and host_x64/pm in the fuchsia build output directory. These directories
    # contain host tools and files necessary to push packages to Fuchsia.
    host_build_dir = build_results.fuchsia_build_dir.join('host_x64')
    archive.add(
        host_build_dir.join('amber-publish'),
        directory=build_results.fuchsia_build_dir)
    archive.add(
        host_build_dir.join('pm'), directory=build_results.fuchsia_build_dir)

    # Add the keys used to sign the OTA metadata.
    # TODO(jmatt): This is a near-term solution for shuffling keys around, we'll
    #   do something better in the future.
    # TODO(dbort): Get the source root from a FuchsiaCheckoutResults instead
    #   of hard-coding. See if we can stuff the FuchsiaCheckoutResults in the
    #   FuchsiaBuildResults; maybe even move the api.build() method onto the
    #   checkout. That may let us remove most 'start_dir' hard-coding from this
    #   module.
    root_dir = self.m.path['start_dir']
    amber_src_dir = root_dir.join('garnet', 'go', 'src', 'amber')
    archive.add(amber_src_dir.join('keys'), amber_src_dir)

    # Tar the files.
    archive.tar('tar fuchsia packages')

    # Return a Path to the tarball.
    return archive.path

  def _tar_breakpad_symbols(self, symbol_files, build_dir):
    """Collects Breakpad symbol files generated by the build into a tarball.

    These are necessary to enable crash reporting.

    Args:
      symbol_files (List(string)): The list of absolute paths to symbol files.
      build_dir (Path): The build directory, which must be a parent path
        of the paths in $symbol_files.

    Returns:
      A Path to a tarball containing symbol files.
    """
    # Create the archive.
    archive = self.m.tar.create(
        self.m.path['cleanup'].join('breakpad_symbols.tar.gz'),
        compression='gzip')

    # Add the symbol files.
    for sf in symbol_files:
      archive.add(sf, build_dir)

    # Tar the files.
    archive.tar('tar breakpad symbols')

    # Return a path to the tarball.
    return archive.path

  def _upload_file_to_gcs(self, path, bucket, hash=True):
    """Uploads a file to a GCS bucket, using the appropriate naming scheme.

    Args:
      path (Path): A path to the file to upload.
      bucket (str): The name of the GCS bucket to upload to.

    Returns:
      The upload step.
    """
    # The destination path is based on the buildbucket ID and the basename
    # of the local file.
    if not self.m.buildbucket.build_id:  # pragma: no cover
      raise self.m.step.StepFailure('buildbucket.build_id is not set')
    basename = self.m.path.basename(path)
    dst = 'builds/%s/%s' % (self.m.buildbucket.build_id, basename)
    return self.m.gsutil.upload(
        bucket=bucket,
        src=path,
        dst=dst,
        link_name=basename,
        name='upload %s to %s' % (basename, bucket))

  def upload_build_artifacts(self,
                             build_results,
                             bucket,
                             upload_breakpad_symbols=False):
    """Uploads artifacts from the build to Google Cloud Storage.

    More specifically, this uploads multiple sets of artifacts:
    * Images and tools necessary to boot Fuchsia.
    * Packages which may be sent to Fuchsia's package manager.
    * Optionally, symbols for the Fuchsia binaries.

    Args:
      build_results (FuchsiaBuildResults): The Fuchsia build results to get
        artifacts from.
      bucket (str): The Google Cloud Storage bucket to upload to.
      upload_breakpad_symbols (bool): If true, uploads breakpad symbols to
        the bucket as well.
    """
    assert bucket

    self.m.gsutil.ensure_gsutil()
    self.m.tar.ensure_tar()

    # Upload Fuchsia boot data.
    archive = self._tar_fuchsia_boot_data(build_results)
    self._upload_file_to_gcs(archive, bucket)

    # Upload fuchsia packages.
    archive = self._tar_fuchsia_packages(build_results)
    self._upload_file_to_gcs(archive, bucket)

    # Upload breakpad symbol files.
    if upload_breakpad_symbols:
      symbol_files = self._get_breakpad_symbol_files(build_results)
      if symbol_files:
        archive = self._tar_breakpad_symbols(symbol_files,
                                             build_results.fuchsia_build_dir)
        self._upload_file_to_gcs(archive, bucket)

  def _get_breakpad_symbol_files(self, build_results):
    """Extracts the list of generated symbol files.

    These symbol files are generated from the build's unstripped binaries and
    are eventually uploaded to the Crash servers to enable crash reporting for
    release builds.

    Args:
      build_results (FuchsiaBuildResults): The build results.

    Returns:
      A list of absolute Paths to each symbol file. All paths in the returned
      list are subpaths of build_results.fuchsia_build_dir.
    """
    # Read the summary generated by //tools/cmd/dump_breakpad_symbols.  The
    # summary is a JSON object whose keys are absolute paths to binaries and
    # values are absolute paths to the generated breakpad symbol files for
    # those binaries.
    binary_to_symbol_file = self.m.json.read(
        name='read symbol file summary',
        path=build_results.fuchsia_build_dir.join('breakpad_symbols',
                                                  'symbol_file_mappings.json'),
    ).json.output

    return list(
        map(self.m.path.abs_to_path, binary_to_symbol_file.itervalues()))

  def _process_coverage(self, test_results, symbolize_dump):
    self.m.gsutil.ensure_gsutil()

    with self.m.context(infra_steps=True):
      cipd_dir = self.m.path['start_dir'].join('cipd')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('fuchsia/tools/covargs/${platform}', 'latest')
      self.m.cipd.ensure(cipd_dir, pkgs)

    host_platform = HOST_PLATFORMS[self.m.platform.arch][self.m.platform.bits]
    downloads_dir = self.m.path['start_dir'].join('zircon', 'prebuilt',
                                                  'downloads')
    clang_dir = downloads_dir.join('clang', 'bin')

    output_dir = self.m.path['cleanup'].join('coverage')
    self.m.step(
        'covargs',
        [
            cipd_dir.join('covargs'),
            '-summary',
            test_results.results_dir.join('summary.json'),
            # TODO: this is already in build_results, maybe we should pass it
            # to this method rather than constructing it manually.
            '-ids',
            test_results.build_dir.join('ids.txt'),
            '-symbolize-dump',
            symbolize_dump,
            '-output-dir',
            output_dir,
            '-llvm-profdata',
            clang_dir.join('llvm-profdata'),
            '-llvm-cov',
            clang_dir.join('llvm-cov'),
        ])

    # TODO: move this into gsutil module/deduplicate this with other GCS logic
    dst = 'builds/%s/coverage' % self.m.buildbucket.build_id
    step_result = self.m.gsutil(
        'cp',
        '-r',
        '-z',
        'html',
        '-a',
        'public-read',
        output_dir,
        'gs://%s/%s' % (self._test_coverage_gcs_bucket, dst),
        name='upload coverage',
        multithreaded=True)
    step_result.presentation.links['index.html'] = self.m.gsutil._http_url(
        self._test_coverage_gcs_bucket, self.m.gsutil.join(dst, 'index.html'),
        True)

  def _tracing_data(self, build_results):
    """Uploads GN and ninja tracing results for this build to GCS"""
    # Only upload if the bucket is specified.
    if self._build_metrics_gcs_bucket:
      self.m.gsutil.ensure_gsutil()

      gn_data = self._extract_gn_tracing_data(build_results)
      ninja_data = self._extract_ninja_tracing_data(build_results)
      self._upload_file_to_gcs(
          gn_data, self._build_metrics_gcs_bucket, hash=False)
      self._upload_file_to_gcs(
          ninja_data, self._build_metrics_gcs_bucket, hash=False)

  def _extract_gn_tracing_data(self, build_results):
    """Extracts the tracing data from this GN run.

    Args:
      build_results (FuchsiaBuildResults): The build results.

    Returns:
      A Path to the file containing the gn tracing data in Chromium's
      about:tracing html format.
    """
    return self._trace2html(self.m.path['cleanup'].join('gn_trace.json'),
                            self.m.path['cleanup'].join('gn_trace.html'))

  def _extract_ninja_tracing_data(self, build_results):
    """Extracts the tracing data from the .ninja_log.

    Args:
      build_results (FuchsiaBuildResults): The build results.

    Returns:
      A Path to the file containing the gn tracing data in Chromium's
      about:tracing html format.
    """
    with self.m.context(infra_steps=True):
      cipd_dir = self.m.path['start_dir'].join('cipd')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('fuchsia/tools/ninjatrace/${platform}', 'latest')
      self.m.cipd.ensure(cipd_dir, pkgs)

    trace = self.m.path['cleanup'].join('ninja_trace.json')
    html = self.m.path['cleanup'].join('ninja_trace.html')
    self.m.step(
        'ninja tracing', [
            self.m.path['start_dir'].join('cipd').join('ninjatrace'),
            '-filename',
            build_results.fuchsia_build_dir.join('.ninja_log'),
            '-trace-json',
            trace,
        ],
        stdout=self.m.raw_io.output(leak_to=trace))
    return self._trace2html(trace, html)

  def _trace2html(self, trace, html):
    """Converts an about:tracing file to HTML using the trace2html tool"""

    # Catapult is imported in manifest/garnet, so we abort if it wasn't included
    # in this checkout.
    # if self.m.path['third_party'].join('catapult') not in self.m.path:
    #     return
    self.m.python(
        name='trace2html',
        script=self.m.path['start_dir'].join('third_party', 'catapult',
                                             'tracing', 'bin', 'trace2html'),
        args=['--output', html, trace])
    return html

  def run_bloaty(self, build_results):
    """Runs bloaty on the specified build results.

    The data is generated by running Bloaty McBloatface on the binaries in the
    build results. If this is called more than once, it will only run once.
      A Path to the file containing the resulting bloaty data.
    """
    if self._build_metrics_gcs_bucket:
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('fuchsia/tools/bloatalyzer/${platform}', 'latest')
        pkgs.add_package('fuchsia/third_party/bloaty/${platform}', 'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

      bloaty_file = self.m.path['cleanup'].join('bloaty.html')
      self.m.step(
          'bloaty',
          [
              self.m.path['start_dir'].join('cipd', 'bloatalyzer'),
              '-bloaty',
              self.m.path['start_dir'].join('cipd', 'bloaty'),
              '-input',
              build_results.ids,
              '-output',
              bloaty_file,
              # We can't include all targets because the page won't load, so limit the output.
              '-top-files',
              '50',
              '-top-syms',
              '50',
              '-format',
              'html',
              # Limit the number of jobs so that we don't overwhelm the bot.
              '-jobs',
              str(min(self.m.platform.cpu_count, 32)),
          ])
      self._upload_file_to_gcs(
          bloaty_file, self._build_metrics_gcs_bucket, hash=False)
