# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import collections
import hashlib
import pipes
import re

# List of available targets.
TARGETS = ['x64', 'arm64']

# The kernel image.
TARGET_TO_KERNEL_IMAGE = dict(zip(
    TARGETS,
    ['zircon.bin', 'qemu-zircon.bin'],
)) # yapf: disable

# Per-target kernel command line.
TARGET_CMDLINE = dict(zip(
    TARGETS,
    [['kernel.serial=legacy'], []]
)) # yapf: disable

# List of available build types.
BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

# The name of the CoW Fuchsia image to create.
FUCHSIA_IMAGE_NAME = 'fuchsia.qcow2'

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

# This is a GN scope; see //build/gn/packages.gni about `synthesize_packages`.
RUNCMDS_PACKAGE_SPEC = '''
{
  name = "infra_runcmds"
  deprecated_system_image = true
  resources = [
    {
      path = "%s"
      dest = "infra/runcmds"
    },
  ]
}
'''

# (variant_name, switch) mapping Fuchsia GN variant names (as used in the
# variant property) to build-zircon.sh switches.
VARIANTS_ZIRCON = [
    ('host_asan', '-H'),
    # TODO(ZX-2197): Don't build Zircon with ASan when building Fuchsia
    # with ASan due to linking problems.  Long run, unclear whether we
    # want to enable ASan in Zircon pieces on Fuchsia ASan bots.
    #('asan', '-A'),
]


# TODO(mknyszek): Figure out whether its safe to derive this from target.
def _board_name(target):
  """Returns the name of the matching "board name" given a target."""
  return {'arm64': 'qemu', 'x64': 'pc'}[target]


class FuchsiaCheckoutResults(object):
  """Represents a Fuchsia source checkout."""

  def __init__(self, root_dir, snapshot_file, snapshot_file_sha1):
    self._root_dir = root_dir
    self._snapshot_file = snapshot_file
    self._snapshot_file_sha1 = snapshot_file_sha1

  @property
  def root_dir(self):
    """The path to the root directory of the jiri checkout."""
    return self._root_dir

  @property
  def snapshot_file(self):
    """The path to the jiri snapshot file."""
    return self._snapshot_file

  @property
  def snapshot_file_sha1(self):
    """The SHA-1 hash of the contents of snapshot_file."""
    return self._snapshot_file_sha1


class FuchsiaBuildResults(object):
  """Represents a completed build of Fuchsia."""

  def __init__(self, target, zircon_build_dir, fuchsia_build_dir, has_tests,
               test_device_type):
    assert target in TARGETS
    self._zircon_build_dir = zircon_build_dir
    self._fuchsia_build_dir = fuchsia_build_dir
    self._target = target
    self._has_tests = has_tests
    self._test_device_type = test_device_type

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
  def has_tests(self):
    """Whether or not this build has the necessary additions to be tested."""
    return self._has_tests

  @property
  def test_device_type(self):
    """The type of device that this build is created to run tests on.

    This will be passed to Swarming as the device_type dimension in testing
    if its value is not 'QEMU'.
    """
    return self._test_device_type

class FuchsiaApi(recipe_api.RecipeApi):
  """APIs for checking out, building, and testing Fuchsia."""

  class FuchsiaTestResults(object):
    """Represents the result of testing of a Fuchsia build."""

    def __init__(self, build_dir, output, outputs, json_api):
      self._build_dir = build_dir
      self._output = output
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
    def build_dir(self):
      """A path to the build directory for symbolization artifacts."""
      return self._build_dir

    @property
    def output(self):
      """Kernel output which may be passed to the symbolizer script."""
      return self._output

    @property
    def outputs(self):
      """A mapping between relative paths for output files to their contents."""
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
    def passed_tests(self):
      return self._filter_by_result(passing=True)

    @property
    def failed_tests(self):
      return self._filter_by_result(passing=False)

    def _filter_by_result(self, passing):
      """Returns all test results that are either passing or failing.

      Args:
        passing (bool): Whether to get only tests that are passing.

      Returns:
        An OrderedDict containing the matched test results. Each key is
        a test name and each value is the test's output.
      """
      matches = collections.OrderedDict()

      # TODO(kjharland): Sort test names first.
      for test in self.summary['tests']:
        if (test['result'] == 'PASS') == passing:
          matches[test['name']] = self.outputs[test['output_file']]

      return matches

  def __init__(self, *args, **kwargs):
    super(FuchsiaApi, self).__init__(*args, **kwargs)

  def checkout(self,
               manifest,
               remote,
               project=None,
               patch_ref=None,
               patch_gerrit_url=None,
               patch_project=None,
               snapshot_gcs_bucket=None,
               timeout_secs=20 * 60):
    """Uses Jiri to check out a Fuchsia project.

    The patch_* arguments must all be set, or none at all.
    The root of the checkout is returned via FuchsiaCheckoutResults.root_dir.

    Args:
      manifest (str): A path to the manifest in the remote (e.g. manifest/minimal)
      remote (str): A URL to the remote repository which Jiri will be pointed at
      project (str): The name of the project
      patch_ref (str): A reference ID to the patch in Gerrit to apply
      patch_gerrit_url (str): A URL of the patch in Gerrit to apply
      patch_project (str): The name of Gerrit project
      snapshot_gcs_bucket (str): The GCS bucket to upload a Jiri snapshot to
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
          project,
          patch_ref,
          patch_gerrit_url,
          patch_project,
          timeout_secs=timeout_secs,
      )

      snapshot_file = self.m.path['cleanup'].join('jiri.snapshot')
      snapshot_contents = self.m.jiri.snapshot(snapshot_file)
      # Always log snapshot contents (even if uploading to GCS) to help debug
      # things like tryjob failures during roller-commits.
      snapshot_step_logs = self.m.step.active_result.presentation.logs
      snapshot_step_logs['snapshot_contents'] = snapshot_contents.split('\n')

      digest = self.m.hash.sha1(
          'hash snapshot',
          snapshot_file,
          test_data='8ac5404b688b34f2d34d1c8a648413aca30b7a97')

      if snapshot_gcs_bucket:
        self.m.gsutil.ensure_gsutil()
        self.m.gsutil.upload(
            bucket=snapshot_gcs_bucket,
            src=snapshot_file,
            dst=digest,
            link_name='jiri.snapshot',
            name='upload jiri.snapshot',
            unauthenticated_url=True)

      # TODO(dbort): Add some or all of the jiri.checkout() params if they
      # become useful.
      return FuchsiaCheckoutResults(
          root_dir=self.m.path['start_dir'],
          snapshot_file=snapshot_file,
          snapshot_file_sha1=digest)

  def _create_runcmds_package(self, test_cmds, test_in_qemu=True):
    """Creates a Fuchsia package which contains a script for running tests automatically."""
    # The device topological path is the toplogical path to the block device
    # which will contain test output.
    device_topological_path = '/dev/sys/pci/00:%s/virtio-block/block' % (
        TEST_FS_PCI_ADDR)

    # Script that mounts the block device to contain test output and runs tests,
    # dropping test output into the block device.
    test_dir = self.target_test_dir()
    runcmds = [
        '#!/boot/bin/sh',
        'mkdir %s' % test_dir,
    ]
    if test_in_qemu:
      runcmds.extend([
          # Wait until the MinFS test image shows up (max <timeout> ms).
          'waitfor class=block topo=%s timeout=60000' % device_topological_path,
          'mount %s %s' % (device_topological_path, test_dir),
      ] + test_cmds + [
          'umount %s' % test_dir,
          'dm poweroff',
      ])
    else:
      runcmds.extend(test_cmds)
    runcmds_path = self.m.path['cleanup'].join('runcmds')
    self.m.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
    self.m.step.active_result.presentation.logs['runcmds'] = runcmds

    runcmds_package_spec = RUNCMDS_PACKAGE_SPEC % runcmds_path
    self.m.step.active_result.presentation.logs['runcmds_package_spec'] = (
        runcmds_package_spec.splitlines())

    return runcmds_package_spec

  def _build_zircon(self, target, variants):
    """Builds zircon for the specified target."""
    cmd = [
        self.m.path['start_dir'].join('scripts', 'build-zircon.sh'),
        '-t',
        target,
    ]
    for variant, switch in VARIANTS_ZIRCON:
      if variant in variants:
        cmd.append(switch)
    cmd += [
        '-j',
        self.m.goma.recommended_goma_jobs,
        'GOMACC=%s' % self.m.goma.goma_dir.join('gomacc'),
    ]
    self.m.step('zircon', cmd)

  def _setup_goma(self):
    """Sets up goma directory and returns an environment for goma."""
    self.m.goma.ensure_goma()

    goma_env = {}
    if self.m.properties.get('goma_local_cache', False):
      goma_env['GOMA_LOCAL_OUTPUT_CACHE_DIR'] = self.m.path['cache'].join(
          'goma', 'localoutputcache')

    return goma_env

  def _build_fuchsia(self, build, build_type, packages, variants, gn_args,
                     ninja_targets):
    """Builds fuchsia given a FuchsiaBuildResults and other GN options."""
    with self.m.step.nest('build fuchsia'):
      args = [
          'target_cpu="%s"' % build.target,
          'fuchsia_packages=[%s]' %
          ','.join('"%s"' % pkg for pkg in packages),
          'use_goma=true',
          'goma_dir="%s"' % self.m.goma.goma_dir,
          'is_debug=%s' % ('true' if build_type == 'debug' else 'false'),
      ]

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

      self.m.step('gn gen', [
          self.m.path['start_dir'].join('buildtools', 'gn'),
          'gen',
          build.fuchsia_build_dir,
          '--check',
          '--args=%s' % ' '.join(args + list(gn_args)),
      ])

      self.m.step('ninja', [
          self.m.path['start_dir'].join('buildtools', 'ninja'),
          '-C',
          build.fuchsia_build_dir,
          '-j',
          self.m.goma.recommended_goma_jobs,
      ] + list(ninja_targets))

  def build(self,
            target,
            build_type,
            packages,
            variants=(),
            gn_args=[],
            ninja_targets=(),
            test_cmds=(),
            test_device_type='QEMU'):
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
      test_cmds (sequence[str]): A sequence of commands to run on the device
        during testing. If empty, no test package will be added to the build.
      test_device_type (str): The type of device that tests will be executed
        on.

    Returns:
      A FuchsiaBuildResults, representing the recently completed build.
    """
    assert target in TARGETS
    assert build_type in BUILD_TYPES

    if test_cmds:
      gn_args.append(
          'synthesize_packages = [ %s ]' %
          self._create_runcmds_package(
              test_cmds=test_cmds, test_in_qemu=(test_device_type == 'QEMU')))

    if build_type == 'debug':
      build_dir = 'debug'
    else:
      build_dir = 'release'
    out_dir = self.m.path['start_dir'].join('out')
    build = FuchsiaBuildResults(
        target=target,
        zircon_build_dir=out_dir.join('build-zircon', 'build-%s' % target),
        fuchsia_build_dir=out_dir.join('%s-%s' % (build_dir, target)),
        has_tests=bool(test_cmds),
        test_device_type=test_device_type,
    )
    with self.m.step.nest('build'):
      with self.m.goma.build_with_goma(env=self._setup_goma()):
        self._build_zircon(target, variants)
        self._build_fuchsia(
            build=build,
            build_type=build_type,
            packages=packages,
            variants=variants,
            gn_args=gn_args,
            ninja_targets=ninja_targets)
    self.m.minfs.minfs_path = out_dir.join('build-zircon', 'tools', 'minfs')
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
      symbolize_result.presentation.status = self.m.step.FAILURE

  def _symbolize_filter(self, build_dir, data):
    """Invokes zircon's symbolization script to symbolize the given data."""
    symbolize_cmd = [
        self.m.path['start_dir'].join('zircon', 'scripts', 'symbolize-filter'),
        build_dir.join('ids.txt'),
    ]
    symbolize_result = self.m.step(
        'symbolize logs',
        symbolize_cmd,
        stdin=self.m.raw_io.input(data=data),
        stdout=self.m.raw_io.output(),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output(
            'blah\nblah\n'))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs[
          'symbolized logs'] = symbolized_lines
      symbolize_result.presentation.status = self.m.step.FAILURE

  # Do both old and new symbolization styles for now.
  def _symbolize(self, build_dir, data):
    self._symbolize_compat(build_dir, data)
    self._symbolize_filter(build_dir, data)

  def _isolate_artifacts(self,
                         kernel_name,
                         ramdisk_name,
                         zircon_build_dir,
                         fuchsia_build_dir,
                         extra_files=()):
    """Isolates known Fuchia build artifacts necessary for testing.

    Args:
      kernel_name (str): The name of the zircon kernel image.
      ramdisk_name (str): The name of the zircon ramdisk image.
      zircon_build_dir (Path): A path to the build artifacts produced by
        building Zircon.
      fuchsia_build_dir (Path): A path to the build artifacts produced by
        building Fuchsia.
      extra_files (seq[Path]): A list of paths which point to additional files
        which will be isolated together with the Fuchsia and Zircon build
        artifacts.

    Returns:
      The isolated hash that may be used to reference and download the
      artifacts.
    """
    self.m.isolated.ensure_isolated(version='latest')
    isolated = self.m.isolated.isolated()

    # Add zircon image to isolated at the top-level.
    isolated.add_file(zircon_build_dir.join(kernel_name), wd=zircon_build_dir)

    # Add ramdisk binary blob to isolated at the top-level.
    isolated.add_file(
        fuchsia_build_dir.join(ramdisk_name), wd=fuchsia_build_dir)

    # Create qcow2 image from FVM_BLOCK_NAME and add to isolated at the top-level.
    self.m.qemu.ensure_qemu(version='latest')
    with self.m.context(cwd=fuchsia_build_dir.join('images')):
      self.m.qemu.create_image(
          image=FUCHSIA_IMAGE_NAME,
          backing_file=FVM_BLOCK_NAME,
          fmt='qcow2',
      )
      isolated.add_file(self.m.context.cwd.join(FVM_BLOCK_NAME))
      isolated.add_file(self.m.context.cwd.join(FUCHSIA_IMAGE_NAME))

    # Add the extra files to isolated at the top-level.
    for path in extra_files:
      isolated.add_file(
          path, wd=self.m.path.abs_to_path(self.m.path.dirname(path)))

    # Archive the isolated.
    return isolated.archive('isolate artifacts')

  def target_test_dir(self):
    """Returns the location of the mounted test directory on the target."""
    return '/tmp/infra-test-output'

  def _test_in_qemu(self, build, timeout_secs, external_network):
    """Tests a Fuchsia build inside of QEMU.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.
      external_network (bool): Whether to give Fuchsia inside QEMU access
        to the external network.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    self.m.swarming.ensure_swarming(version='latest')

    kernel_name = build.zircon_kernel_image
    ramdisk_name = 'bootdata-blob-%s.bin' % _board_name(build.target)
    qemu_arch = {
        'arm64': 'aarch64',
        'x64': 'x86_64',
    }[build.target]

    cmdline = [
        'zircon.autorun.system=/system/data/infra/runcmds',
        'kernel.halt-on-panic=true',
    ] + TARGET_CMDLINE[build.target]

    # As part of running tests, we'll send a MinFS image over to another machine
    # which will be declared as a block device in QEMU, at which point
    # Fuchsia will mount it and write test output to. input_image_name refers to
    # the name of the image as its created by this recipe, and sent off to the
    # test machine. output_image_name refers to the name of the image as its
    # returned back from the other machine.
    input_image_name = 'input.fs'
    output_image_name = 'output.fs'

    qemu_cmd = [
      './qemu/bin/qemu-system-' + qemu_arch, # Dropped in by CIPD.
      '-m', '4096',
      '-smp', '4',
      '-nographic',
      '-machine', {'aarch64': 'virt,gic_version=host', 'x86_64': 'q35'}[qemu_arch],
      '-kernel', kernel_name,
      '-serial', 'stdio',
      '-monitor', 'none',
      '-initrd', ramdisk_name,
      '-enable-kvm', '-cpu', 'host',
      '-append', ' '.join(cmdline),

      '-drive', 'file=%s,format=qcow2,if=none,id=maindisk' % FUCHSIA_IMAGE_NAME,
      '-device', 'virtio-blk-pci,drive=maindisk',

      '-drive', 'file=%s,format=raw,if=none,id=testdisk' % output_image_name,
      '-device', 'virtio-blk-pci,drive=testdisk,addr=%s' % TEST_FS_PCI_ADDR,
    ] # yapf: disable

    # If we don't need the network, explicitly disable it.
    if not external_network:
      qemu_cmd.extend(['-net', 'none'])

    # Create a qemu runner script which trivially copies the blank MinFS image
    # to hold test results, in order to work around a bug in swarming where
    # modifying cached isolate downloads will modify the cache contents.
    #
    # TODO(mknyszek): Once the isolate bug (http://crbug.com/812925) gets fixed,
    # don't send a runner script to the bot anymore, since we don't need to do
    # this hack to cp the image.
    qemu_runner_script = [
        '#!/bin/sh',
        'cp %s %s' % (input_image_name, output_image_name),
        ' '.join(map(pipes.quote, qemu_cmd)),
    ]

    # Write the QEMU runner to disk so that we can isolate it.
    qemu_runner_name = 'run-qemu.sh'
    qemu_runner = self.m.path['start_dir'].join(qemu_runner_name)
    self.m.file.write_text(
        'write qemu runner',
        qemu_runner,
        '\n'.join(qemu_runner_script),
    )
    self.m.step.active_result.presentation.logs[
        qemu_runner_name] = qemu_runner_script

    # Create MinFS image (which will hold test output). We choose to make the
    # MinFS image 16M because our current test output takes up ~1.5 MB in an
    # absolute worst case (holding all Topaz + Zircon tests), so 16M is chosen
    # because it is ~10x more space than we need.
    test_image = self.m.path['start_dir'].join(input_image_name)
    self.m.minfs.create(test_image, '16M', name='create test image')

    # Isolate the Fuchsia build artifacts in addition to the test image and the
    # qemu runner.
    isolated_hash = self._isolate_artifacts(
        kernel_name,
        ramdisk_name,
        build.zircon_build_dir,
        build.fuchsia_build_dir,
        extra_files=[
            test_image,
            qemu_runner,
        ],
    )

    qemu_cipd_arch = {
        'arm64': 'arm64',
        'x64': 'amd64',
    }[build.target]

    dimension_cpu = {
        'arm64': 'arm64',
        'x64': 'x86-64',
    }[build.target]

    with self.m.context(infra_steps=True):
      # Trigger task.
      trigger_result = self.m.swarming.trigger(
          'all tests',
          ['/bin/sh', qemu_runner_name],
          isolated=isolated_hash,
          dump_json=self.m.path.join(self.m.path['cleanup'],
                                     'qemu_test_results.json'),
          dimensions={
              'pool': 'fuchsia.tests',
              'os': 'Debian',
              'cpu': dimension_cpu,
              'kvm': '1',
          },
          io_timeout=TEST_IO_TIMEOUT_SECS,
          hard_timeout=timeout_secs,
          outputs=[output_image_name],
          cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch,
                          'latest')],
      )
      # Collect results.
      results = self.m.swarming.collect(
          requests_json=self.m.json.input(trigger_result.json.output))
      assert len(results) == 1
      result = results[0]
    self.analyze_collect_result('task results', result, build.zircon_build_dir)

    # Extract test results.
    test_results_dir = self.m.path['start_dir'].join('test_results')
    with self.m.context(infra_steps=True):
      test_results_map = self.m.minfs.copy_image(
          step_name='extract results',
          image_path=result[output_image_name],
          out_dir=test_results_dir,
      ).raw_io.output_dir
    return self.FuchsiaTestResults(
        build_dir=build.fuchsia_build_dir,
        output=result.output,
        outputs=test_results_map,
        json_api=self.m.json,
    )

  def _test_on_device(self, build, timeout_secs):
    """Tests a Fuchsia on a specific device.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    self.m.swarming.ensure_swarming(version='latest')

    # Construct the botanist command.
    kernel_name = build.zircon_kernel_image
    ramdisk_name = 'netboot.bin'
    output_archive_name = 'out.tar'
    botanist_cmd = [
        './botanist/botanist',
        '-config', '/etc/botanist/config.json',
        '-kernel', kernel_name,
        '-ramdisk', ramdisk_name,
        '-test', self.target_test_dir(),
        '-out', output_archive_name,
        'zircon.autorun.system=/system/data/infra/runcmds',
    ] # yapf: disable

    # Isolate the Fuchsia build artifacts.
    isolated_hash = self._isolate_artifacts(
        kernel_name,
        ramdisk_name,
        build.zircon_build_dir,
        build.fuchsia_build_dir,
    )

    with self.m.context(infra_steps=True):
      # Trigger task.
      trigger_result = self.m.swarming.trigger(
          'all tests',
          botanist_cmd,
          isolated=isolated_hash,
          dimensions={
              'pool': 'fuchsia.tests',
              'device_type': build.test_device_type,
          },
          io_timeout=TEST_IO_TIMEOUT_SECS,
          hard_timeout=timeout_secs,
          outputs=[output_archive_name],
          cipd_packages=[('botanist', 'fuchsia/infra/botanist/linux-amd64',
                          'latest')],
      )
      # Collect results.
      results = self.m.swarming.collect(
          requests_json=self.m.json.input(trigger_result.json.output))
      assert len(results) == 1
      result = results[0]
    self.analyze_collect_result('task results', result, build.zircon_build_dir)

    # Extract test results.
    test_results_dir = self.m.path['start_dir'].join('test_results')
    with self.m.context(infra_steps=True):
      self.m.tar.ensure_tar()
      test_results_map = self.m.tar.extract(
          step_name='extract results',
          archive=result[output_archive_name],
          dir=self.m.raw_io.output_dir(leak_to=test_results_dir),
      ).raw_io.output_dir
    return self.FuchsiaTestResults(
        build_dir=build.fuchsia_build_dir,
        output=result.output,
        outputs=test_results_map,
        json_api=self.m.json,
    )

  def test(self, build, timeout_secs=40 * 60, external_network=False):
    """Tests a Fuchsia build on the specified device.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.
      external_network (bool): Whether to enable access to the external
        network when executing tests. Ignored if
        build.test_device_type != 'QEMU'.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    assert build.has_tests
    if build.test_device_type == 'QEMU':
      return self._test_in_qemu(
          build=build,
          timeout_secs=timeout_secs,
          external_network=external_network,
      )
    else:
      return self._test_on_device(build, timeout_secs)

  def analyze_collect_result(self, step_name, result, zircon_build_dir):
    """Analyzes a swarming.CollectResult and reports results as a step.

    Args:
      step_name (str): The display name of the step for this analysis.
      result (swarming.CollectResult): The swarming collection result to analyze.
      zircon_build_dir (Path): A path to the zircon build directory for symbolization
        artifacts.

    Raises:
      A StepFailure if a kernel panic is detected, or if the tests timed out.
      An InfraFailure if the swarming task failed for a different reason.
    """
    step_result = self.m.step(step_name, None)
    kernel_output_lines = result.output.split('\n')
    step_result.presentation.logs['kernel log'] = kernel_output_lines
    if result.is_infra_failure():
      raise self.m.step.InfraFailure('Failed to collect: %s' % result.output)
    elif result.is_failure():
      if result.timed_out():
        # If we have a timeout with a successful collect, then this must be an
        # io_timeout failure, since task timeout > collect timeout.
        step_result.presentation.step_text = 'i/o timeout'
        step_result.presentation.status = self.m.step.FAILURE
        self._symbolize(zircon_build_dir, result.output)
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
      self._symbolize(zircon_build_dir, result.output)
      raise self.m.step.StepFailure(
          'Found kernel panic. See symbolized output for details.')

  def analyze_test_results(self, step_name, test_results):
    """Analyzes test results represented by a FuchsiaTestResults.

    Args:
      step_name (str): The name of the step under which to test the analysis steps.
      test_results (FuchsiaTestResults): The test results.

    Raises:
      A StepFailure if any of the discovered tests failed.
    """
    with self.m.step.nest(step_name):
      # Log the results of each test.
      self.report_test_results(test_results)

      if test_results.failed_tests:
        # Symbolize test output to help debug failures.
        self._symbolize(test_results.build_dir, test_results.output)
        # Halt with a step failure.
        raise self.m.step.StepFailure(
          'Test failure(s): ' + ', '.join(test_results.failed_tests.keys()))

  def report_test_results(self, test_results):
    """Logs individual test results in separate steps.

    Args:
      test_results (FuchsiaTestResults): The test results.
    """
    if not test_results.summary:
      self._symbolize(test_results.build_dir, test_results.output)
      # Halt with step failure if summary file is missing.
      raise self.m.step.StepFailure(
          'Test summary JSON not found, see kernel log for details')

    # Log the summary file's contents.
    raw_summary_log = test_results.raw_summary.split('\n')
    self.m.step.active_result.presentation.logs['summary.json'] = raw_summary_log

    for test in test_results.summary['tests']:
      test_name = test['name']
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
