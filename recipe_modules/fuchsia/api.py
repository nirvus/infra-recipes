# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import collections
import hashlib
import re


# List of available targets.
TARGETS = ['arm64', 'x86-64']

# List of available build types.
BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

# The kernel binary to pass to qemu.
ZIRCON_IMAGE_NAME = 'zircon.bin'

# The boot filesystem image.
BOOTFS_IMAGE_NAME = 'user.bootfs'

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


def _zircon_project(target):
  """Returns the zircon project for the target string."""
  return {'arm64': 'arm64', 'x86-64': 'x86'}[target]


def _gn_target(target):
  """Returns the GN target for the target string."""
  return {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]


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
  def fuchsia_build_dir(self):
    """The directory where Fuchsia build artifacts may be found."""
    return self._fuchsia_build_dir

  @property
  def has_tests(self):
    """Whether or not this build has the necessary additions to be tested."""
    return self._has_tests


class FuchsiaApi(recipe_api.RecipeApi):
  """APIs for checking out, building, and testing Fuchsia."""

  def __init__(self, *args, **kwargs):
    super(FuchsiaApi, self).__init__(*args, **kwargs)

  def checkout(self, manifest, remote, project=None, patch_ref=None,
               patch_gerrit_url=None, patch_project=None, upload_snapshot=False):
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
    """
    self.m.jiri.ensure_jiri()
    self.m.jiri.checkout(
        manifest,
        remote,
        project,
        patch_ref,
        patch_gerrit_url,
        patch_project,
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

  def _create_runcmds_package(self, runtests_args):
    """Creates a Fuchsia package which contains a script for running tests automatically."""
    runcmds = [
      '#!/boot/bin/sh',
      'msleep 5000',
      # TODO(mknyszek): Remove this ASAP. Auto-mount the image instead by
      # using minfs + fvm to create an image with a GPT and GUID 'DATA'.
      #
      # This will be a source of flake long-term as '000' will soon
      # frequently NOT be '000'.
      'mount /dev/class/block/000 /data',
      'runtests -o /data ' + runtests_args,
      'dm poweroff',
    ]
    runcmds_path = self.m.path['tmp_base'].join('runcmds')
    self.m.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
    self.m.step.active_result.presentation.logs['runcmds'] = runcmds

    runcmds_package_path = self.m.path['tmp_base'].join('runcmds_package')
    runcmds_package = RUNCMDS_PACKAGE % runcmds_path
    self.m.file.write_text('write runcmds package', runcmds_package_path, runcmds_package)
    self.m.step.active_result.presentation.logs['runcmds_package'] = runcmds_package.splitlines()
    return str(runcmds_package_path)

  def _build_zircon(self, target):
    """Builds zircon for the specified target."""
    self.m.step('zircon', [
      self.m.path['start_dir'].join('scripts', 'build-zircon.sh'),
      '-c',
      '-H',
      '-p', _zircon_project(target),
    ])

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

  def _build_fuchsia(self, build, build_type, packages, variants, gn_args):
    """Builds fuchsia given a FuchsiaBuildResults and other GN options."""
    goma_env = self._setup_goma()
    with self.m.step.nest('build fuchsia'):
      with self.m.goma.build_with_goma(env=goma_env):
        gen_cmd = [
          self.m.path['start_dir'].join('build', 'gn', 'gen.py'),
          '--target_cpu=%s' % _gn_target(build.target),
          '--packages=%s' % ','.join(packages),
          '--platforms=%s' % _zircon_project(build.target),
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

        self.m.step('ninja', ninja_cmd)

  def build(self, target, build_type, packages, variants, gn_args,
            include_tests=False, runtests_args=''):
    """Builds Fuchsia from a Jiri checkout.

    Expects a Fuchsia Jiri checkout at api.path['start_dir'].

    Args:
      target (str): The build target, see TARGETS for allowed targets
      build_type (str): One of the build types in BUILD_TYPES
      packages (list[str]): A list of packages to pass to GN to build
      variants (list[str]): A list of build variants to pass to gen.py via
        --variant
      gn_args (list[str]): Additional arguments to pass to GN
      include_tests (bool): Whether to include a package in the build for
        automatically executing tests
      runtests_args (str): Space-separated arguments to pass to the test driver
        if include_tests is set

    Returns:
      A FuchsiaBuildResults, representing the recently completed build.
    """
    assert target in TARGETS
    assert build_type in BUILD_TYPES

    # TODO(abarth): Remove once INTK-99 is fixed.
    packages.append('build/packages/bootfs')

    if include_tests:
      packages.append(self._create_runcmds_package(runtests_args))

    if build_type == 'debug':
      build_dir = 'debug'
    else:
      build_dir = 'release'
    out_dir = self.m.path['start_dir'].join('out')
    build = FuchsiaBuildResults(
        target=target,
        zircon_build_dir=out_dir.join('build-zircon', 'build-%s' % _zircon_project(target)),
        fuchsia_build_dir=out_dir.join('%s-%s' % (build_dir, _gn_target(target))),
        has_tests=include_tests,
    )
    with self.m.step.nest('build'):
      self._build_zircon(target)
      self._build_fuchsia(build, build_type, packages, variants, gn_args)
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

  def _isolate_artifacts(self, zircon_build_dir, fuchsia_build_dir):
    """Isolates artifacts necessary for testing."""
    self.m.isolated.ensure_isolated(version='latest')

    test_image = self.m.path['start_dir'].join('test.fs')
    self.m.minfs.create(test_image, '32M', name='create test image')

    isolated = self.m.isolated.isolated()
    isolated.add_file(test_image, wd=self.m.path['start_dir'])
    isolated.add_file(zircon_build_dir.join(ZIRCON_IMAGE_NAME), wd=zircon_build_dir)
    isolated.add_file(fuchsia_build_dir.join(BOOTFS_IMAGE_NAME), wd=fuchsia_build_dir)
    return isolated.archive('isolate %s and %s' % (ZIRCON_IMAGE_NAME, BOOTFS_IMAGE_NAME))

  def test(self, build):
    """Tests a Fuchsia build.

    Expects the build and artifacts to be at the same place they were at
    the end of the build.

    Args:
      build (FuchsiaBuildResults): The Fuchsia build to test
    """
    assert build.has_tests

    isolated_hash = self._isolate_artifacts(
        build.zircon_build_dir,
        build.fuchsia_build_dir,
    )
    self.m.swarming.ensure_swarming(version='latest')

    qemu_arch = {
      'arm64': 'aarch64',
      'x86-64': 'x86_64',
    }[build.target]

    cmdline = [
      'zircon.autorun.system=/system/data/infra/runcmds',
      'kernel.halt-on-panic=true',
    ]

    qemu_cmd = [
      './qemu/bin/qemu-system-' + qemu_arch, # Dropped in by CIPD.
      '-m', '4096',
      '-smp', '4',
      '-nographic',
      '-machine', {'aarch64': 'virt,gic_version=host', 'x86_64': 'q35'}[qemu_arch],
      '-kernel', ZIRCON_IMAGE_NAME,
      '-serial', 'stdio',
      '-monitor', 'none',
      '-initrd', BOOTFS_IMAGE_NAME,
      '-enable-kvm', '-cpu', 'host',
      '-append', ' '.join(cmdline),
      '-drive', 'file=test.fs,format=raw,if=none,id=mydisk',
      '-device', 'ahci,id=ahci',
      '-device', 'ide-drive,drive=mydisk,bus=ahci.0',
    ]

    qemu_cipd_arch = {
      'arm64': 'arm64',
      'x86-64': 'amd64',
    }[build.target]

    with self.m.context(infra_steps=True):
      # Trigger task.
      trigger_result = self.m.swarming.trigger(
          'all tests',
          qemu_cmd,
          isolated=isolated_hash,
          dump_json=self.m.path.join(self.m.path['tmp_base'], 'qemu_test_results.json'),
          dimensions={
            'pool': 'fuchsia.tests',
            'os':   'Debian',
            'cpu':  build.target,
            'kvm':  '1',
          },
          io_timeout=TEST_IO_TIMEOUT_SECS,
          outputs=['test.fs'],
          cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
      )
      # Collect results.
      results = self.m.swarming.collect('20m', requests_json=self.m.json.input(trigger_result.json.output))
      assert len(results) == 1
      result = results[0]

    step_result = self.m.step('task results', None)
    kernel_output_lines = result.output.split('\n')
    step_result.presentation.logs['output'] = kernel_output_lines
    if result.is_infra_failure():
      raise self.m.step.InfraFailure('Failed to collect: %s' % result.output)
    elif result.is_failure():
      # If the kernel panics, chances are it will result in a task failure since
      # the task will likely time out and QEMU will be forcibly killed.
      if 'KERNEL PANIC' in result.output:
        step_result.presentation.step_text = 'kernel panic'
        step_result.presentation.status = self.m.step.FAILURE
        self._symbolize(build.zircon_build_dir, result.output)
        raise self.m.step.StepFailure('Found kernel panic. See symbolized output for details.')
      # If we have a timeout with a successful collect, then this must be an
      # io_timeout failure, since task timeout > collect timeout.
      if result.timed_out():
        step_result.presentation.step_text = 'i/o timeout'
        step_result.presentation.status = self.m.step.FAILURE
        self._symbolize(build.zircon_build_dir, result.output)
        failure_lines = [
          'I/O timed out, no output for %s seconds.' % TEST_IO_TIMEOUT_SECS,
          'Last 10 lines of kernel output:',
        ] + kernel_output_lines[-10:]
        raise self.m.step.StepFailure('\n'.join(failure_lines))
      # At this point its likely an infra issue with QEMU,
      # though a deadlock might also reach this state.
      step_result.presentation.status = self.m.step.EXCEPTION
      raise self.m.step.InfraFailure('Swarming task failed:\n%s' % result.output)

    test_results_dir = self.m.path['start_dir'].join('minfs_isolate_results')
    with self.m.context(infra_steps=True):
      # Copy test results out of image.
      test_output = self.m.minfs.cp(
          # Paths inside of the MinFS image are prefixed with '::', so '::'
          # refers to the root of the MinFS image.
          '::',
          self.m.raw_io.output_dir(leak_to=test_results_dir),
          result['test.fs'],
          name='extract test results',
          step_test_data=lambda: self.m.raw_io.test_api.output_dir({
              'hello.out': 'I am output.'
          }),
      ).raw_io.output_dir
      # Read the tests summary.
      test_summary = self.m.json.read(
          'read test summary',
          test_results_dir.join('summary.json'),
          step_test_data=lambda: self.m.json.test_api.output({
              'tests': [{'name': '/hello', 'result': 'PASS'}],
          }),
      ).json.output

    # Report test results.
    failed_tests = collections.OrderedDict()
    with self.m.step.nest('tests'):
      for test in test_summary['tests']:
        name = test['name']
        step_result = self.m.step(name, None)
        # TODO(mknyszek): make output_name more consistently map to name.
        output_name = name + '.out'
        assert output_name.startswith('/')
        output_name = output_name[1:]
        step_result.presentation.logs['stdio'] = test_output[output_name].split('\n')
        if test['result'] != 'PASS':
          step_result.presentation.status = self.m.step.FAILURE
          failed_tests[name] = test_output[output_name]

    # Symbolize the output of any failed tests.
    if failed_tests:
      self._symbolize(build.fuchsia_build_dir, '\n'.join(failed_tests.values()))
      raise self.m.step.StepFailure('Test failure(s): ' + ', '.join(failed_tests.keys()))