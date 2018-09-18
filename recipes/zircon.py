# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Zircon."""

import contextlib
import pipes
import re

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property, StepFailure


DEPS = [
  'infra/cipd',
  'infra/fuchsia',
  'infra/goma',
  'infra/jiri',
  'infra/isolated',
  'infra/minfs',
  'infra/qemu',
  'infra/swarming',
  'infra/tar',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/source_manifest',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

TARGETS = ['x64', 'arm64']
# TODO(dbort): Add a new class to manage these mappings more clearly.
TARGET_TO_ARCH = dict(zip(
    TARGETS,
    ['x86_64', 'aarch64'],
))

# The name of the Zircon ZBI image produced by the build. Contains both kernel
# and a ramdisk.
ZIRCON_ZBI_NAME = 'zircon.zbi'

# The kernel image.
TARGET_TO_KERNEL_IMAGE = dict(zip(
    TARGETS,
    ['multiboot.bin', 'qemu-boot-shim.bin'],
))
ARCHS = ('x86_64', 'aarch64')

# Supported device types for testing.
DEVICES = ('QEMU', 'Intel NUC Kit NUC6i3SYK', 'Intel NUC Kit NUC7i5DNHE', 'HiKey 960')

# toolchain: (['make', 'args'], 'builddir-suffix')
TOOLCHAINS = {
  'gcc': ([], ''),
  'clang': (['USE_CLANG=true'], '-clang'),
  'asan': (['USE_ASAN=true'], '-asan'),
  'lto': (['USE_LTO=true', 'USE_THINLTO=false'], '-lto'),
  'profile': (['USE_PROFILE=true'], '-profile'),
  'thinlto': (['USE_LTO=true', 'USE_THINLTO=true'], '-thinlto'),
}

# The path under /boot to the runcmds script (which runs tests) in the zircon
# bootfs.
RUNCMDS_BOOTFS_PATH = 'infra/runcmds'

# The PCI address to use for the block device to contain test results. This value
# is somewhat arbitrary, but it works very consistently and appears to be a safe
# PCI address value to use within QEMU.
TEST_FS_PCI_ADDR = '06.0'

# How long to wait (in seconds) before killing the test swarming task if there's
# no output being produced.
TEST_IO_TIMEOUT_SECS = 60

# This string matches the one in //zircon/system/utest/core/main.c.
CORE_TESTS_SUCCESS_STR = 'core-tests succeeded RZMm59f7zOSs6aZUIXZR'

# Common to all NUC devices: block device path for use by blktest and other
# destructive local storage tests.
NUC_SCRATCH_BLOCK_DEVICE_PATH = '/dev/sys/pci/00:17.0/ahci/sata2/block'

# Key is device_type recipe property.
# Val is a block device path for use by blktest and other destructive local
# storage tests. 'Scratch' here means it can be destroyed by the tests.
# Destructive local storage tests will run on a given device type iff that
# device type is present in this dict.
DEVICE_TYPE_TO_SCRATCH_BLOCK_DEVICE_PATH = {
    'Intel NUC Kit NUC6i3SYK': NUC_SCRATCH_BLOCK_DEVICE_PATH,
    'Intel NUC Kit NUC7i5DNHE': NUC_SCRATCH_BLOCK_DEVICE_PATH,
}

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'revision': Property(kind=str, help='Revision of manifest to import',
                       default=None),
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'toolchain': Property(kind=Enum(*(TOOLCHAINS.keys())),
                        help='Toolchain to use'),
  'make_args': Property(kind=List(basestring),
                        help='Extra args to pass to Make',
                        default=[]),
  'run_tests' : Property(kind=bool, help='Run tests in qemu after building', default=True),
  'runtests_args': Property(kind=str,
                            help='Shell-quoted string to add to the runtests commandline',
                            default=''),
  'use_kvm': Property(kind=bool,
                      help='Whether to use KVM when running tests in QEMU',
                      default=True),
  'device_type': Property(kind=Enum(*DEVICES),
                          help='The type of device to execute tests on',
                          default='QEMU'),
  'run_host_tests': Property(kind=bool,
                             help='Run host tests after building',
                             default=False),
}


def RunTestsOnHost(api, build_dir):
  """Runs host tests.

  Args:
    build_dir (Path): Path to the build directory.
  """
  runtests = build_dir.join('tools', 'runtests')
  host_test_dir = build_dir.join('host_tests')

  # Write test results to the 'host' subdirectory of |results_dir_on_host|
  # so as not to collide with target test results.
  test_results_dir = api.fuchsia.results_dir_on_host.join('host')

  # In order to symbolize host ASan output, the llvm symbolizer must be in
  # one's PATH and the path to the symbolizer must be set as
  # ASAN_SYMBOLIZER_PATH. See the following for documentation:
  # https://clang.llvm.org/docs/AddressSanitizer.html#symbolizing-the-reports
  llvm_symbolizer = api.path['start_dir'].join(
      'zircon', 'prebuilt', 'downloads', 'clang', 'bin', 'llvm-symbolizer')
  with api.context(env={"ASAN_SYMBOLIZER_PATH": llvm_symbolizer}):

    # Allow the runtests invocation to fail without resulting in a step failure.
    # The relevant, individual test failures will be reported during the
    # processing of summary.json - and an early step failure will prevent this.
    api.step(
        'run host tests', [
            runtests,
            '-o',
            api.raw_io.output_dir(leak_to=test_results_dir),
            host_test_dir,
        ],
        ok_ret='any')

  # Extract test results.
  test_results_map = api.step.active_result.raw_io.output_dir
  api.fuchsia.analyze_test_results(
      'host test results',
      api.fuchsia.FuchsiaTestResults(
          build_dir=build_dir,
          results_dir=test_results_dir,
          zircon_kernel_log=None,  # We did not run tests on target.
          outputs=test_results_map,
          json_api=api.json,
      )
  )


def RunTestsOnDevice(api, target, build_dir, device_type):
  """Executes Zircon tests on a hardware device.

  Args
    api (recipe_engine.Api): The recipe engine API for this recipe.
    target (str): The zircon target architecture to execute tests on.
    build_dir (Path): Path to the build directory.
    device_type (Enum(*DEVICES)): The type of device to run tests on.
  """
  output_archive_name = 'out.tar'
  botanist_cmd = [
    './botanist/botanist',
    'zedboot',
    '-kernel', ZIRCON_ZBI_NAME,
    '-results-dir', api.fuchsia.results_dir_on_target,
    '-out', output_archive_name,
    'zircon.autorun.boot=/boot/bin/sh+/boot/' + RUNCMDS_BOOTFS_PATH,
  ]

  # Isolate all necessary build artifacts.
  isolated = api.isolated.isolated()
  isolated.add_file(build_dir.join(ZIRCON_ZBI_NAME), wd=build_dir)
  digest = isolated.archive('isolate zircon artifacts')

  with api.context(infra_steps=True):
    # Trigger task.
    trigger_result = api.swarming.trigger(
        'booted tests',
        botanist_cmd,
        isolated=digest,
        dimensions={
          'pool': 'fuchsia.tests',
          'device_type': device_type,
        },
        io_timeout=TEST_IO_TIMEOUT_SECS,
        hard_timeout=40*60, # 40 minute hard timeout
        outputs=[output_archive_name],
        cipd_packages=[('botanist', 'fuchsia/infra/botanist/linux-amd64', 'latest')],
    )
    # Collect results.
    results = api.swarming.collect(requests_json=api.json.input(trigger_result.json.output))
    # This assert just makes sure that we only get 1 result back, as requested.
    # If this assert fails, it indicates a fatal error in our stack.
    assert len(results) == 1
    result = results[0]
  api.fuchsia.analyze_collect_result('task results', result, build_dir)

  # Extract test results.
  test_results_dir = api.fuchsia.results_dir_on_host.join('target')
  with api.context(infra_steps=True):
    api.tar.ensure_tar()
    test_results_map = api.tar.extract(
        step_name='extract results',
        path=result[output_archive_name],
        directory=api.raw_io.output_dir(leak_to=test_results_dir),
    ).raw_io.output_dir

  # Analyze the test results and report them in the presentation.
  api.fuchsia.analyze_test_results(
    'booted test results',
    api.fuchsia.FuchsiaTestResults(
        build_dir=build_dir,
        results_dir=test_results_dir,
        zircon_kernel_log=result.output,
        outputs=test_results_map,
        json_api=api.json,
    )
  )

def RunTestsInQEMU(api, target, build_dir, use_kvm):
  """Executes Zircon tests in QEMU on a different machine.

  Args:
    api (recipe_engine.Api): The recipe engine API for this recipe.
    target (str): The zircon target architecture to execute tests on.
    build_dir (Path): Path to the build directory.
    use_kvm (bool): Whether or not to enable KVM with QEMU when testing.
  """
  arch = TARGET_TO_ARCH[target]
  assert arch in ARCHS

  # Generate a MinFS image which will hold test results. This will later be
  # declared as a block device to QEMU and will then be mounted by the
  # runcmds script. The size of the MinFS should be large enough to
  # accomodate all test results and test output. The current size is picked
  # to be able to safely hold test results for quite some time (as of 03/18
  # the space used is very roughly on the order of a megabyte). Having a
  # larger-image-than-necessary isn't a big deal for isolate, which
  # compresses the image before uploading.
  minfs_image_name = 'output.fs'
  minfs_image = api.path['start_dir'].join(minfs_image_name)
  api.minfs.create(minfs_image, '16M', name='create minfs image')

  # Generate the botanist QEMU commands.
  base_botanist_cmd = [
    './botanist/botanist',
    'qemu',
    '-qemu-dir', './qemu/bin',
    '-qemu-kernel', TARGET_TO_KERNEL_IMAGE[target],
    '-zircon-a', ZIRCON_ZBI_NAME,
    '-arch', target,
  ] # yapf: disable
  if use_kvm:
    base_botanist_cmd.append('-use-kvm')

  core_tests_botanist_cmd = base_botanist_cmd + [
    # executes bin/core-tests in place of userspace.
    'userboot=bin/core-tests',
    # shuts down zircon after the userboot process exits.
    'userboot.shutdown',
  ] # yapf: disable

  booted_tests_botanist_cmd = base_botanist_cmd + [
      '-minfs', minfs_image_name,
      '-pci-addr', TEST_FS_PCI_ADDR,
      # On boot, execute the RUNCMDS script.
      'zircon.autorun.boot=/boot/bin/sh+/boot/%s' % RUNCMDS_BOOTFS_PATH,
  ] # yapf: disable

  # Isolate all necessary build artifacts as well as the MinFS image.
  isolated = api.isolated.isolated()
  isolated.add_file(build_dir.join(TARGET_TO_KERNEL_IMAGE[target]), wd=build_dir)
  isolated.add_file(build_dir.join(ZIRCON_ZBI_NAME), wd=build_dir)
  isolated.add_file(minfs_image, wd=api.path['start_dir'])
  digest = isolated.archive('isolate zircon artifacts')

  # Trigger a task that runs the core tests in place of userspace at boot.
  core_task = TriggerTestsTask(
      api=api,
      name='core tests',
      cmd=core_tests_botanist_cmd,
      arch=arch,
      use_kvm=use_kvm,
      isolated_hash=digest,
      timeout_secs=10*60, # 10 minute hard timeout.
  )
  # Trigger a task that runs tests in the standard way with runtests and
  # the runcmds script.
  booted_task = TriggerTestsTask(
      api=api,
      name='booted tests',
      cmd=booted_tests_botanist_cmd,
      arch=arch,
      use_kvm=use_kvm,
      isolated_hash=digest,
      output=minfs_image_name,
      timeout_secs=40*60, # 40 minute hard timeout.
  )

  # Collect task results and analyze.
  FinalizeTestsTasks(api, core_task, booted_task, minfs_image_name, build_dir)

def TriggerTestsTask(api, name, cmd, arch, use_kvm, isolated_hash, output='',
                     timeout_secs=60*60):
  """TriggerTestsTask triggers a task to execute a command on a remote machine.

  The remote machine is guaranteed to have QEMU and botanist installed

  Args:
    api: Recipe engine API object.
    name (str): Name of the task.
    cmd (seq[str]): The command to execute with each argument as a separate
      list entry.
    arch (str): The target architecture to execute tests for.
    use_kvm (bool): Whether or not a bot with KVM should be requested for the
      task.
    isolated_hash (str): A digest of the isolated containing the build
      artifacts.
    output (str): Optional relative path to an output file on the target
      machine which will be isolated and returned back to the machine
      executing this recipe.
    timeout_secs (int): The amount of seconds the task should run for before
      timing out.

  Returns:
    The task ID of the triggered task.
  """
  # If we're not using KVM, we'll be executing on an x86 machine, so we need to
  # make sure we're dropping in the correct binaries.
  if not use_kvm:
    cipd_arch = 'amd64'
  else:
    cipd_arch = {
      'aarch64': 'arm64',
      'x86_64': 'amd64',
    }[arch]

  dimensions = {
    'pool': 'fuchsia.tests',
    'os':   'Debian',
  }
  if use_kvm:
    dimensions['cpu'] = {'aarch64': 'arm64', 'x86_64': 'x86-64'}[arch]
    dimensions['kvm'] = '1'
  else:
    # If we're not using KVM, we should use our x86 testers since we'll be in
    # full emulation mode anyway, and our arm64 resources are much fewer in
    # number.
    dimensions['cpu'] = 'x86-64'

  with api.context(infra_steps=True):
    # Trigger task.
    trigger_result = api.swarming.trigger(
        name,
        cmd,
        isolated=isolated_hash,
        dimensions=dimensions,
        hard_timeout=timeout_secs,
        io_timeout=TEST_IO_TIMEOUT_SECS,
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % cipd_arch, 'latest'),
                       ('botanist', 'fuchsia/infra/botanist/linux-%s' % cipd_arch, 'latest')],
        outputs=[output] if output else None,
    ).json.output
    assert 'tasks' in trigger_result and len(trigger_result['tasks']) == 1
    return trigger_result['tasks'][0]['task_id']


def FinalizeTestsTasks(api, core_task, booted_task, booted_task_output_image,
                       build_dir):
  """Waits on the tasks running core tests and booted tests, then analyzes the
  results.

  Args:
    core_task (str): The swarming task ID of the task running core tests.
    booted_task (str): The swarming task ID of the task running booted tests.
    build_dir (Path): A path to the directory containing build artifacts.
  """
  with api.context(infra_steps=True):
    collect_results = api.swarming.collect(tasks=[core_task, booted_task])
  results_map = {r.id: r for r in collect_results}

  # Analyze core tests results.
  api.fuchsia.analyze_collect_result(
      'core tests task results',
      results_map[core_task],
      build_dir,
  )

  # Because of the way these tests run (they are the only user-mode process in
  # the system, and then the system shuts down) we can't collect an exit code or
  # nicely structured output, so we have to search the output for a hard-coded
  # string to detect success.
  if CORE_TESTS_SUCCESS_STR not in results_map[core_task].output:
    raise StepFailure(
        'Did not find string "%s" in kernel log, so assuming core tests '
        'failed.' % CORE_TESTS_SUCCESS_STR)

  # Analyze booted tests results just like the fuchsia recipe module does.
  booted_result = results_map[booted_task]
  api.fuchsia.analyze_collect_result(
      'booted tests task results',
      booted_result,
      build_dir,
  )

  # Extract test results from the MinFS image.
  test_results_dir = api.fuchsia.results_dir_on_host.join('target')
  test_results_map = api.minfs.copy_image(
      step_name='extract results',
      image_path=booted_result[booted_task_output_image],
      out_dir=test_results_dir,
  ).raw_io.output_dir

  # Analyze the test results and report them in the presentation.
  api.fuchsia.analyze_test_results(
    'booted test results',
    api.fuchsia.FuchsiaTestResults(
        build_dir=build_dir,
        results_dir=test_results_dir,
        zircon_kernel_log=booted_result.output,
        outputs=test_results_map,
        json_api=api.json,
  ))


def _BlockDeviceTestExtraUserManifestLines(api, tmp_dir, block_device_path):
  extra_user_manifest_lines = []
  # Tuple of (test name, command).
  commands = [
      ('blktest', 'blktest -d %s' % block_device_path),
      ('fs-test-minfs',
          '/boot/test/fs/fs-test -f minfs -d %s' % block_device_path),
      # value for -c is block count, should be small enough to let the test run
      # in < 30 seconds.
      ('iochk', 'iochk -c 16384 --live-dangerously %s' % block_device_path)]
  for name, command in commands:
    test_sh = ['#!/boot/bin/sh',
               command,
               'TEST_EXIT_CODE="$?"',
               'if [ "$TEST_EXIT_CODE" -ne 0 ]; then',
               # lsblk output may be useful to debug.
               '  echo "lsblk output:"',
               '  lsblk',
               '  exit "$TEST_EXIT_CODE"',
               'fi']
    test_sh_basename = '%s.sh' % name
    test_sh_path = tmp_dir.join(test_sh_basename)
    api.file.write_text(
        'write %s_sh' % name, test_sh_path, '\n'.join(test_sh))
    api.step.active_result.presentation.logs[test_sh_basename] = test_sh
    # Put it under test/fs/ so that runtests finds it. See kDefaultTestDirs in
    # runtests.
    extra_user_manifest_lines.append(
        'test/fs/%s=%s' % (test_sh_basename, test_sh_path))

  return extra_user_manifest_lines


def Build(api, target, toolchain, make_args, src_dir, test_cmd, needs_blkdev,
          device_type):
  """Builds zircon and returns a path to the build output directory."""
  # Generate runcmds script to drive tests.
  tmp_dir = api.path['cleanup'].join('zircon_tmp')
  api.file.ensure_directory('makedirs tmp', tmp_dir)
  runcmds_path = tmp_dir.join('runcmds')
  # In the use_isolate case, we need to mount a block device to write test
  # results and test output to. Thus, the runcmds script must:
  results_dir_on_target = api.fuchsia.results_dir_on_target
  runcmds = [
    # 1. Make a test directory.
    'mkdir %s' % results_dir_on_target,
  ]
  if needs_blkdev:
    # If we need a block device to get test output off Fuchsia, then we need
    # to mount a MinFS image which we'll declare as a block device to QEMU at
    # PCI address TEST_FS_PCI_ADDR.
    #
    # This topological path is the path on the device to the MinFS image as a
    # raw block device.
    device_topological_path = '/dev/sys/pci/00:%s/virtio-block/block' % TEST_FS_PCI_ADDR
    runcmds.extend([
      # 2. Wait for devmgr to bring up the MinFS test output image (max
      # <timeout> ms).
      'waitfor class=block topo=%s timeout=60000' % device_topological_path,
      # 3. Mount the block device to the new test directory.
      'mount %s %s' % (device_topological_path, results_dir_on_target),
      # 4. Execute the desired test command.
      test_cmd,
      # 5. Unmount and poweroff.
      'umount %s' % results_dir_on_target,
      'dm poweroff',
    ])
  else:
    # If we don't need a block device, just run the tests and wait for
    # something to copy the test results off. Note that in this case we do not
    # power off the device (via `dm poweroff`).
    runcmds.extend([test_cmd])
  api.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
  api.step.active_result.presentation.logs['runcmds.sh'] = runcmds

  # The bootfs manifest is a list of mappings between bootfs paths and local
  # file paths. The syntax is roughly:
  # install/path/under/boot=path/to/file/or/dir.
  extra_user_manifest_lines = ['%s=%s' % (RUNCMDS_BOOTFS_PATH, runcmds_path)]

  # Unfortuantely there's currently no way for the test to discover the block
  # device to use on its own, so we have to construct this script here, once we
  # know what device type we're using. See IN-459 for discussion.
  block_device_path = DEVICE_TYPE_TO_SCRATCH_BLOCK_DEVICE_PATH.get(device_type)
  if block_device_path:
    extra_user_manifest_lines.extend(
        _BlockDeviceTestExtraUserManifestLines(api, tmp_dir, block_device_path))

  with api.step.nest('build'):
    # Set up toolchain and build args.
    tc_args, tc_suffix = TOOLCHAINS[toolchain]
    build_args = [
      'make',
      target,
      'GOMACC=%s' % api.goma.goma_dir.join('gomacc'),
      '-j', api.goma.jobs,
      'HOST_USE_ASAN=true',
      'BUILDROOT=%s' % src_dir,
    ] + make_args + tc_args

    # If thinlto build, it needs a cache. Pass it a directory in the cache
    # directory.
    if toolchain == 'thinlto':
      build_args.append('THINLTO_CACHE_DIR=' +
                        str(api.path['cache'].join('thinlto')))

    build_args.append('EXTRA_USER_MANIFEST_LINES=%s' %
                      ' '.join(extra_user_manifest_lines))

    # Build zircon.
    with api.goma.build_with_goma(), api.context(cwd=src_dir):
      api.step('build', build_args)

  # Return the location of the build artifacts.
  return src_dir.join('build-%s' % target + tc_suffix)


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, patch_storage,
             patch_repository_url, project, manifest, remote, revision,
             target, toolchain, make_args, use_kvm, run_tests, runtests_args,
             device_type, run_host_tests):
  api.goma.ensure_goma()
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest=manifest,
                      remote=remote,
                      project=project,
                      revision=revision,
                      patch_ref=patch_ref,
                      patch_gerrit_url=patch_gerrit_url,
                      patch_project=patch_project)

  src_dir = api.path['start_dir'].join('zircon')
  build_dir = Build(
      api=api,
      target=target,
      toolchain=toolchain,
      make_args=make_args,
      src_dir=src_dir,
      test_cmd='runtests -o %s %s' % (
          api.fuchsia.results_dir_on_target,
          runtests_args,
      ),
      needs_blkdev=(device_type == 'QEMU'),
      device_type=device_type,
  )

  if run_tests:
    api.qemu.ensure_qemu()
    api.swarming.ensure_swarming(version='latest')
    api.isolated.ensure_isolated(version='latest')
    if device_type == 'QEMU':
      # The MinFS tool is generated during the Zircon build, so only after we
      # build may we set the recipe module's tool path.
      api.minfs.minfs_path = build_dir.join('tools', 'minfs')

      # Execute tests.
      RunTestsInQEMU(api, target, build_dir, use_kvm)
    else:
      RunTestsOnDevice(api, target, build_dir, device_type)
  if run_host_tests:
    RunTestsOnHost(api, build_dir)


def GenTests(api):
  # Step test data for triggering the booted tests task.
  booted_tests_trigger_data = api.step_data(
      'trigger booted tests',
      api.swarming.trigger(
          'booted tests',
          'qemu',
          task_id='11',
      ),
  )
  # Step test data for collecting core and booted tasks.
  core_task_datum = api.swarming.task_success(
      id='10', output=CORE_TESTS_SUCCESS_STR, outputs=['output.fs'])
  booted_task_datum = api.swarming.task_success(id='11', outputs=['output.fs'])
  collect_data = api.step_data('collect', api.swarming.collect(
      task_data=(core_task_datum, booted_task_datum)))
  # Step test data for triggering the core tests task.
  core_tests_trigger_data = api.step_data(
      'trigger core tests',
      api.swarming.trigger(
          'core tests',
          'qemu',
          task_id='10',
      ),
  )
  yield (api.test('ci_arm64') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='arm64',
                     toolchain='gcc') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('ci_arm64_nokvm') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='arm64',
                     toolchain='gcc',
                     use_kvm=False) +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('ci_host_tests') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc',
                     run_tests=False,
                     run_host_tests=True))
  yield (api.test('ci_host_and_target_tests') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc',
                     run_tests=True,
                     run_host_tests=True) +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('ci_x86') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('ci_x86_with_args') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     runtests_args='-L',
                     toolchain='gcc') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('ci_x86_nokvm') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc',
                     use_kvm=False) +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)

  # Exercise all device types, since some recipe logic changes for certain
  # devices.
  for device_type in DEVICES:
    if device_type == 'QEMU':
      # QEMU is the default, well-exercised by other tests.
      continue
    test_name = 'ci_device_' + re.sub(r'\s+', '_', device_type)
    yield (api.test(test_name) +
        api.properties(project='zircon',
                       manifest='manifest',
                       remote='https://fuchsia.googlesource.com/zircon',
                       target='x64',
                       toolchain='gcc',
                       device_type=device_type) +
        booted_tests_trigger_data +
        api.step_data('collect', api.swarming.collect(
            task_data=[api.swarming.task_success(outputs=['out.tar'])],
        )))

  yield (api.test('task_failure') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      api.step_data('collect', api.swarming.collect(
          task_data=[api.swarming.task_failure(id='10'),
                     api.swarming.task_failure(id='11')]
      )))
  yield (api.test('asan') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x64',
                    toolchain='asan') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('lto') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x64',
                    toolchain='lto') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('thinlto') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x64',
                    toolchain='thinlto') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('cq_try') +
     api.properties.tryserver(
         gerrit_project='zircon',
         patch_gerrit_url='fuchsia-review.googlesource.com',
         project='zircon',
         manifest='manifest',
         remote='https://fuchsia.googlesource.com/zircon',
         target='x64',
         toolchain='clang') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
  yield (api.test('no_run_tests') +
     api.properties.tryserver(
         project='zircon',
         manifest='manifest',
         remote='https://fuchsia.googlesource.com/zircon',
         target='x64',
         toolchain='clang',
         run_tests=False))
  yield (api.test('debug_buildonly') +
     api.properties.tryserver(
         project='zircon',
         manifest='manifest',
         remote='https://fuchsia.googlesource.com/zircon',
         target='x64',
         toolchain='clang',
         make_args=['DEBUG_HARD=1'],
         run_tests=False))

  # This task should trigger a failure because its output does not contain
  # CORE_TESTS_SUCCESS_STR
  failed_core_task_datum = api.swarming.task_success(
      id='10', output='not success')
  core_tests_failed_collect_data = api.step_data(
      'collect',
      api.swarming.collect(task_data=(failed_core_task_datum, booted_task_datum)
      ))
  yield (api.test('ci_core_test_failure') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='clang') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      core_tests_failed_collect_data)
