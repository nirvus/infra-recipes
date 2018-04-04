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
))

# List of available build types.
BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

# The name of the CoW Fuchsia image to create.
FUCHSIA_IMAGE_NAME = 'fuchsia.qcow2'

# The FVM block name.
FVM_BLOCK_NAME = 'fvm.blk'

# The PCI address to use for the block device to contain test results.
TEST_FS_PCI_ADDR = '06.0'

# How long to wait (in seconds) before killing the test swarming task if there's
# no output being produced.
TEST_IO_TIMEOUT_SECS = 60

RUNCMDS_PACKAGE = '''
{
    "resources": [
        {
            "bootfs_path": "data/infra/runcmds",
            "file": "%s"
        }
    ]
}
'''

# (variant_name, switch) mapping Fuchsia GN variant names (as used in the
# variant property) to build-zircon.sh switches.
VARIANTS_ZIRCON = [
  ('host_asan', '-H'),
  ('asan', '-A'),
]


# TODO(mknyszek): Figure out whether its safe to derive this from target.
def _board_name(target):
  """Returns the name of the matching "board name" given a target."""
  return {'arm64': 'qemu', 'x64': 'pc'}[target]


class FuchsiaBuildResults(object):
  """Represents a completed build of Fuchsia."""
  def __init__(self, target, zircon_build_dir, fuchsia_build_dir, has_tests):
    assert target in TARGETS
    self._zircon_build_dir = zircon_build_dir
    self._fuchsia_build_dir = fuchsia_build_dir
    self._target = target
    self._has_tests = has_tests

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


class FuchsiaApi(recipe_api.RecipeApi):
  """APIs for checking out, building, and testing Fuchsia."""

  class FuchsiaTestResults(object):
    """Represents the result of testing of a Fuchsia build."""
    def __init__(self, build_dir, output, outputs):
      self._build_dir = build_dir
      self._output = output
      self._outputs = outputs

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


  def __init__(self, *args, **kwargs):
    super(FuchsiaApi, self).__init__(*args, **kwargs)

  def checkout(self, manifest, remote, project=None, patch_ref=None,
               patch_gerrit_url=None, patch_project=None, upload_snapshot=False,
               timeout_secs=20*60):
    """Uses Jiri to check out a Fuchsia project.

    The patch_* arguments must all be set, or none at all.
    The checkout is made into api.path['start_dir'].

    Args:
      manifest (str): A path to the manifest in the remote (e.g. manifest/minimal)
      remote (str): A URL to the remote repository which Jiri will be pointed at
      project (str): The name of the project
      patch_ref (str): A reference ID to the patch in Gerrit to apply
      patch_gerrit_url (str): A URL of the patch in Gerrit to apply
      patch_project (str): The name of Gerrit project
      upload_snapshot (bool): Whether to upload a Jiri snapshot to GCS
      timeout_secs (int): How long to wait for the checkout to complete
          before failing
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
      if patch_ref:
        self.m.jiri.update(gc=True, rebase_tracked=True, local_manifest=True)
      if upload_snapshot:
        self.m.gsutil.ensure_gsutil()
        snapshot_file = self.m.path['tmp_base'].join('jiri.snapshot')
        self.m.jiri.snapshot(snapshot_file)
        digest = self.m.hash.sha1('hash snapshot', snapshot_file,
                                  test_data='8ac5404b688b34f2d34d1c8a648413aca30b7a97')
        self.m.gsutil.upload('fuchsia-snapshots', snapshot_file, digest,
          link_name='jiri.snapshot',
          name='upload jiri.snapshot',
          unauthenticated_url=True)

  def _create_runcmds_package(self, test_cmds, test_in_qemu=True):
    """Creates a Fuchsia package which contains a script for running tests automatically."""
    # The device topological path is the toplogical path to the block device
    # which will contain test output.
    device_topological_path = '/dev/sys/pci/00:%s/virtio-block/block' % (
        TEST_FS_PCI_ADDR,
    )

    # Script that mounts the block device to contain test output and runs tests,
    # dropping test output into the block device.
    test_dir = self.target_test_dir()
    runcmds = [
      '#!/boot/bin/sh',
      # TODO(ZX-1903): Replace this with a way to block until PCI enumeration
      # has finished.
      'msleep 5000',
      'mkdir %s' % test_dir,
    ]
    if test_in_qemu:
      runcmds.extend([
        'mount %s %s' % (device_topological_path, test_dir),
      ] + test_cmds + [
        'umount %s' % test_dir,
        'dm poweroff',
      ])
    else:
      runcmds.extend(test_cmds)
    runcmds_path = self.m.path['tmp_base'].join('runcmds')
    self.m.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
    self.m.step.active_result.presentation.logs['runcmds'] = runcmds

    runcmds_package_path = self.m.path['tmp_base'].join('runcmds_package')
    runcmds_package = RUNCMDS_PACKAGE % runcmds_path
    self.m.file.write_text('write runcmds package', runcmds_package_path, runcmds_package)
    self.m.step.active_result.presentation.logs['runcmds_package'] = runcmds_package.splitlines()
    return str(runcmds_package_path)

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
    self.m.step('zircon', cmd)

  def _setup_goma(self):
    """Sets up goma directory and returns an environment for goma."""
    goma_dir = self.m.properties.get('goma_dir', None)
    if goma_dir:
      self.m.goma.set_goma_dir(goma_dir)

    self.m.goma.ensure_goma()

    goma_env = {}
    if self.m.properties.get('goma_local_cache', False):
      goma_env['GOMA_LOCAL_OUTPUT_CACHE_DIR'] = self.m.path['cache'].join('goma', 'localoutputcache')

    return goma_env

  def _build_fuchsia(self, build, build_type, packages, variants,
                     gn_args, ninja_targets):
    """Builds fuchsia given a FuchsiaBuildResults and other GN options."""
    goma_env = self._setup_goma()
    with self.m.step.nest('build fuchsia'):
      with self.m.goma.build_with_goma(env=goma_env):
        gen_cmd = [
          self.m.path['start_dir'].join('build', 'gn', 'gen.py'),
          '--target_cpu=%s' % build.target,
          '--packages=%s' % ','.join(packages),
        ]

        gen_cmd += ['--variant=%s' % v for v in variants]

        gen_cmd.append('--goma=%s' % self.m.goma.goma_dir)

        if build_type != 'debug':
          gen_cmd.append('--release')

        if build_type == 'lto':
          gen_cmd.append('--lto=full')
        elif build_type == 'thinlto':
          gen_cmd.append('--lto=thin')
          gn_args.append('thinlto_cache_dir=\"%s\"' %
                         str(self.m.path['cache'].join('thinlto')))

        for arg in gn_args:
          gen_cmd.append('--args')
          gen_cmd.append(arg)

        self.m.step('gen', gen_cmd)

        ninja_cmd = [
          self.m.path['start_dir'].join('buildtools', 'ninja'),
          '-C', build.fuchsia_build_dir,
        ]

        ninja_cmd.extend(['-j', self.m.goma.recommended_goma_jobs])
        ninja_cmd.extend(ninja_targets)

        self.m.step('ninja', ninja_cmd)

  def build(self, target, build_type, packages, variants=(), gn_args=(),
            ninja_targets=(), test_cmds=(), test_in_qemu=True):
    """Builds Fuchsia from a Jiri checkout.

    Expects a Fuchsia Jiri checkout at api.path['start_dir'].

    Args:
      target (str): The build target, see TARGETS for allowed targets
      build_type (str): One of the build types in BUILD_TYPES
      packages (sequence[str]): A sequence of packages to pass to GN to build
      variants (sequence[str]): A sequence of build variants to pass to gen.py
        via --variant
      gn_args (sequence[str]): Additional arguments to pass to GN
      ninja_targets (sequence[str]): Additional target args to pass to ninja
      test_cmds (sequence[str]): A sequence of commands to run on the device
        during testing. If empty, no test package will be added to the build.
      test_in_qemu (bool): Whether or not the tests will be run in QEMU.

    Returns:
      A FuchsiaBuildResults, representing the recently completed build.
    """
    assert target in TARGETS
    assert build_type in BUILD_TYPES

    if test_cmds:
      packages.append(self._create_runcmds_package(test_cmds, test_in_qemu))

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
    )
    with self.m.step.nest('build'):
      self._build_zircon(target, variants)
      self._build_fuchsia(build=build, build_type=build_type, packages=packages,
                          variants=variants, gn_args=gn_args,
                          ninja_targets=ninja_targets)
    self.m.minfs.minfs_path = out_dir.join('build-zircon', 'tools', 'minfs')
    return build

  def _symbolize(self, build_dir, data):
    """Invokes zircon's symbolization script to symbolize the given data."""
    symbolize_cmd = [
      self.m.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
      '--no-echo',
      '--build-dir', build_dir,
    ]
    symbolize_result = self.m.step('symbolize', symbolize_cmd,
        stdin=self.m.raw_io.input(data=data),
        stdout=self.m.raw_io.output(),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized backtraces'] = symbolized_lines
      symbolize_result.presentation.status = self.m.step.FAILURE

  def _isolate_artifacts(self, kernel_name, ramdisk_name, zircon_build_dir, fuchsia_build_dir, extra_files=()):
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
    isolated.add_file(fuchsia_build_dir.join(ramdisk_name), wd=fuchsia_build_dir)

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
      isolated.add_file(path, wd=self.m.path.abs_to_path(self.m.path.dirname(path)))

    # Archive the isolated.
    return isolated.archive('isolate artifacts')

  def target_test_dir(self):
    """Returns the location of the mounted test directory on the target."""
    return '/tmp/infra-test-output'

  def test(self, build, timeout_secs=40*60):
    """Tests a Fuchsia build inside of QEMU.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    assert build.has_tests
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
    ]

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
    ]

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
    self.m.step.active_result.presentation.logs[qemu_runner_name] = qemu_runner_script

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
          dump_json=self.m.path.join(self.m.path['tmp_base'], 'qemu_test_results.json'),
          dimensions={
            'pool': 'fuchsia.tests',
            'os':   'Debian',
            'cpu':  dimension_cpu,
            'kvm':  '1',
          },
          io_timeout=TEST_IO_TIMEOUT_SECS,
          hard_timeout=timeout_secs,
          outputs=[output_image_name],
          cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
      )
      # Collect results.
      results = self.m.swarming.collect(requests_json=self.m.json.input(trigger_result.json.output))
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
    )

  def test_on_device(self, device_type, build, timeout_secs=40*60):
    """Tests a Fuchsia on a specific device.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      device_type (str): The type of device to run tests on. This will be
        passed to swarming as the device_type dimension.
      build (FuchsiaBuildResults): The Fuchsia build to test.
      timeout_secs (int): The amount of seconds to wait for the tests to
        execute before giving up.

    Returns:
      A FuchsiaTestResults representing the completed test.
    """
    assert build.has_tests
    self.m.swarming.ensure_swarming(version='latest')

    # Construct the botanist command.
    kernel_name = build.zircon_kernel_image
    ramdisk_name = 'netboot-%s.bin' % _board_name(build.target)
    output_archive_name = 'out.tar'
    botanist_cmd = [
      './botanist/botanist',
      '-config', '/etc/botanist/config.json',
      '-kernel', kernel_name,
      '-ramdisk', ramdisk_name,
      '-test', self.target_test_dir(),
      '-out', output_archive_name,
      'zircon.autorun.system=/system/data/infra/runcmds',
    ]

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
            'device_type': device_type,
          },
          io_timeout=TEST_IO_TIMEOUT_SECS,
          hard_timeout=timeout_secs,
          outputs=[output_archive_name],
          cipd_packages=[('botanist', 'fuchsia/infra/botanist/linux-amd64', 'latest')],
      )
      # Collect results.
      results = self.m.swarming.collect(requests_json=self.m.json.input(trigger_result.json.output))
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
    )

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
      raise self.m.step.InfraFailure('Swarming task failed:\n%s' % result.output)
    elif 'KERNEL PANIC' in result.output:
      step_result.presentation.step_text = 'kernel panic'
      step_result.presentation.status = self.m.step.FAILURE
      self._symbolize(zircon_build_dir, result.output)
      raise self.m.step.StepFailure('Found kernel panic. See symbolized output for details.')

  def analyze_test_results(self, step_name, test_results):
    """Analyzes test results represented by a FuchsiaTestResults.

    Args:
      step_name (str): The name of the step under which to test the analysis steps.
      test_results (FuchsiaTestResults): The test results.

    Raises:
      A StepFailure if any of the discovered tests failed.
    """
    build_dir = test_results.build_dir
    output = test_results.output
    outputs = test_results.outputs

    with self.m.step.nest(step_name):
      # Read the tests summary.
      if 'summary.json' not in outputs:
        raise self.m.step.StepFailure('Test summary JSON not found, see kernel log for details')
      raw_summary = outputs['summary.json']
      self.m.step.active_result.presentation.logs['summary.json'] = raw_summary.split('\n')
      test_summary = self.m.json.loads(raw_summary)

      # Report test results.
      failed_tests = collections.OrderedDict()
      for test in test_summary['tests']:
        name = test['name']
        step_result = self.m.step(name, None)
        output_name = test['output_file']
        step_result.presentation.logs['stdio'] = outputs[output_name].split('\n')
        if test['result'] != 'PASS':
          step_result.presentation.status = self.m.step.FAILURE
          failed_tests[name] = outputs[output_name]

    # Symbolize the kernel output if any tests failed.
    if failed_tests:
      self._symbolize(build_dir, output)
      raise self.m.step.StepFailure('Test failure(s): ' + ', '.join(failed_tests.keys()))
