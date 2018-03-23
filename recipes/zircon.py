# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Zircon."""

import contextlib
import pipes
import re

from recipe_engine.config import Enum
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
# The kernel image.
TARGET_TO_KERNEL_IMAGE = dict(zip(
    TARGETS,
    ['zircon.bin', 'qemu-zircon.bin'],
))
# The boot filesystem image.
TARGET_TO_BOOT_IMAGE = dict(zip(
    TARGETS,
    ['bootdata.bin', 'qemu-bootdata.bin'],
))
ARCHS = ('x86_64', 'aarch64')

# Supported device types for testing.
DEVICES = ['QEMU', 'Intel NUC Kit NUC6i3SYK']

# Per-target kernel command line.
TARGET_CMDLINE = dict(zip(
    TARGETS,
    [['kernel.serial=legacy'], []]
))

# toolchain: (['make', 'args'], 'builddir-suffix')
TOOLCHAINS = {
  'gcc': ([], ''),
  'clang': (['USE_CLANG=true'], '-clang'),
  'asan': (['USE_ASAN=true'], '-asan'),
  'lto': (['USE_LTO=true', 'USE_THINLTO=false'], '-lto'),
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

# Exit code that QEMU may return if running Zircon on x64.
# More specifically, this is necessary because for Zircon to shutdown graceful
# when it's executing core-tests (e.g. kernel command line
# "userboot=bin/core-tests userboot.shutdown") it writes a value to a specially
# declared I/O port. That value ("val") is used to compute the return code as
# ("val" << 1) | 1, which effectively means it will always be odd and non-zero.
# This magic number of 31 is that computed return code.
ZIRCON_QEMU_SUCCESS_CODE = 31

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'toolchain': Property(kind=Enum(*(TOOLCHAINS.keys())),
                        help='Toolchain to use'),
  'run_tests' : Property(kind=bool, help='Run tests in qemu after building', default=True),
  'goma_dir': Property(kind=str, help='Path to goma', default=None),
  'use_kvm': Property(kind=bool,
                      help='Whether to use KVM when running tests in QEMU',
                      default=True),
  'device_type': Property(kind=Enum(*DEVICES),
                          help='The type of device to execute tests on',
                          default='QEMU'),
}


@contextlib.contextmanager
def no_goma():
    yield


def RunTestsOnDevice(api, target, build_dir, device_type):
  """Executes Zircon tests on a hardware device.

  Args:
    api (recipe_engine.Api): The recipe engine API for this recipe.
    target (str): The zircon target architecture to execute tests on.
    build_dir (Path): Path to the build directory.
    device_type (Enum(*DEVICES)): The type of device to run tests on.
  """
  kernel_name = TARGET_TO_KERNEL_IMAGE[target]
  ramdisk_name = TARGET_TO_BOOT_IMAGE[target]
  output_archive_name = 'out.tar'
  botanist_cmd = [
    './botanist/botanist',
    '-kernel', kernel_name,
    '-ramdisk', ramdisk_name,
    '-test', api.fuchsia.target_test_dir(),
    '-out', output_archive_name,
    'zircon.autorun.boot=/boot/' + RUNCMDS_BOOTFS_PATH,
  ]

  # Isolate all necessary build artifacts.
  isolated = api.isolated.isolated()
  isolated.add_file(build_dir.join(kernel_name), wd=build_dir)
  isolated.add_file(build_dir.join(ramdisk_name), wd=build_dir)
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
  test_results_dir = api.path['start_dir'].join('test_results')
  with api.context(infra_steps=True):
    api.tar.ensure_tar()
    test_results_map = api.tar.extract(
        step_name='extract results',
        archive=result[output_archive_name],
        dir=api.raw_io.output_dir(leak_to=test_results_dir),
    ).raw_io.output_dir

  # Analyze the test results and report them in the presentation.
  api.fuchsia.analyze_test_results(
    'booted test results',
    api.fuchsia.FuchsiaTestResults(
        build_dir=build_dir,
        output=result.output,
        outputs=test_results_map,
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

  # As part of running tests, we'll send a MinFS image over to another machine
  # which will be declared as a block device in QEMU, at which point
  # Zircon will mount it and write test output to. input_image_name refers to
  # the name of the image as its created by this recipe, and sent off to the
  # test machine. output_image_name refers to the name of the image as its
  # returned back from the other machine.
  input_image_name = 'input.fs'
  output_image_name = 'output.fs'

  # Generate a MinFS image which will hold test results. This will later be
  # declared as a block device to QEMU and will then be mounted by the
  # runcmds script. The size of the MinFS should be large enough to
  # accomodate all test results and test output. The current size is picked
  # to be able to safely hold test results for quite some time (as of 03/18
  # the space used is very roughly on the order of a megabyte). Having a
  # larger-image-than-necessary isn't a big deal for isolate, which
  # compresses the image before uploading.
  test_image = api.path['start_dir'].join(input_image_name)
  api.minfs.create(test_image, '16M', name='create test image')

  # Generate the QEMU commands.
  core_tests_qemu_cmd = GenerateQEMUCommand(target=target, cmdline=[
    'userboot=bin/core-tests', # executes bin/core-tests in place of userspace.
    'userboot.shutdown', # shuts down zircon after the userboot process exits.
  ], use_kvm=use_kvm)
  booted_tests_qemu_cmd = GenerateQEMUCommand(
      target=target,
      # On boot, execute the RUNCMDS script.
      cmdline=['zircon.autorun.boot=/boot/' + RUNCMDS_BOOTFS_PATH],
      use_kvm=use_kvm,
      blkdev=output_image_name,
  )

  # When executing core-tests, QEMU's return code will be
  # ZIRCON_QEMU_SUCCESS_CODE on x64 due to the way userboot.shutdown is
  # initiated. Catch that here, and exit gracefully with a return code of 0
  # so Swarming doesn't report a failure.
  qemu_runner_core_name = 'run-qemu-core.sh'
  qemu_runner_core = api.path['start_dir'].join(qemu_runner_core_name)
  qemu_runner_core_script = [
    '#!/bin/sh',
    ' '.join(map(pipes.quote, core_tests_qemu_cmd)),
  ]
  if target == 'x64':
    qemu_runner_core_script.extend([
      'rc=$?',
      'if [ "$rc" -eq "%d" ]; then' % ZIRCON_QEMU_SUCCESS_CODE,
      '  exit 0',
      'fi',
      'exit $rc',
    ])
  api.file.write_text(
      'write qemu runner for core-tests',
      qemu_runner_core,
      '\n'.join(qemu_runner_core_script),
  )

  # Create a qemu runner script which trivially copies the blank MinFS image
  # to hold test results, in order to work around a bug in swarming where
  # modifying cached isolate downloads will modify the cache contents.
  #
  # TODO(mknyszek): Once the isolate bug (http://crbug.com/812925) gets fixed,
  # don't send a runner script to the bot anymore, since we don't need to do
  # this hack to cp the image.
  qemu_runner_name = 'run-qemu.sh'
  qemu_runner = api.path['start_dir'].join(qemu_runner_name)
  qemu_runner_script = [
    '#!/bin/sh',
    'cp %s %s' % (input_image_name, output_image_name),
    ' '.join(map(pipes.quote, booted_tests_qemu_cmd)),
  ]
  api.file.write_text(
      'write qemu runner',
      qemu_runner,
      '\n'.join(qemu_runner_script),
  )

  # Isolate all necessary build artifacts as well as the MinFS image.
  isolated = api.isolated.isolated()
  isolated.add_file(build_dir.join(TARGET_TO_KERNEL_IMAGE[target]), wd=build_dir)
  isolated.add_file(build_dir.join(TARGET_TO_BOOT_IMAGE[target]), wd=build_dir)
  isolated.add_file(test_image, wd=api.path['start_dir'])
  isolated.add_file(qemu_runner_core, wd=api.path['start_dir'])
  isolated.add_file(qemu_runner, wd=api.path['start_dir'])
  digest = isolated.archive('isolate zircon artifacts')

  # Trigger a task that runs the core tests in place of userspace at boot.
  core_task = TriggerTestsTask(
      api=api,
      name='core tests',
      cmd=['/bin/sh', './' + qemu_runner_core_name],
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
      # Swarming will drop qemu_runner_name into the PWD in the new task.
      cmd=['/bin/sh', './' + qemu_runner_name],
      arch=arch,
      use_kvm=use_kvm,
      isolated_hash=digest,
      output=output_image_name,
      timeout_secs=40*60, # 40 minute hard timeout.
  )

  # Collect task results and analyze.
  FinalizeTestsTasks(api, core_task, booted_task, output_image_name,
                     build_dir)


def GenerateQEMUCommand(target, cmdline, use_kvm, blkdev=''):
  """GenerateQEMUCommand generates a QEMU command for executing Zircon tests.

  Args:
    target (str): The zircon target architecture to execute tests for.
    cmdline (list[str]): A list of kernel command line arguments to pass to
      zircon.
    use_kvm (bool): Whether or not KVM should be enabled in the QEMU command.
    blkdev (str): Optional relative path to an image name on the test machine.
      If blkdev is non-empty, the triggered task will have QEMU declare an
      additional block device with the backing image being a file located at
      the relative path provided. The image must be on the test machine prior
      to command execution, so it should get there either via CIPD or isolated.

  Returns:
    A list[str] representing QEMU command which invokes QEMU from the default
    CIPD installation directory.
  """
  arch = TARGET_TO_ARCH[target]
  assert arch in ARCHS

  qemu_cmd = [
    './qemu/bin/qemu-system-' + arch, # Dropped in by CIPD.
    '-m', '4096',
    '-smp', '4',
    '-nographic',
    '-kernel', TARGET_TO_KERNEL_IMAGE[target],
    '-serial', 'stdio',
    '-monitor', 'none',
    '-initrd', TARGET_TO_BOOT_IMAGE[target],
    '-append', ' '.join(['TERM=dumb', 'kernel.halt-on-panic=true'] +
                        TARGET_CMDLINE[target] + cmdline),
  ]

  if arch == 'aarch64':
    machine = 'virt'
    if use_kvm:
      machine += ',gic_version=host'
  elif arch == 'x86_64':
    machine = 'q35'
    # Necessary for userboot.shutdown to trigger properly, since it writes to
    # 0xf4 to debug-exit in QEMU.
    qemu_cmd.extend(['-device', 'isa-debug-exit,iobase=0xf4,iosize=0x04'])
  qemu_cmd.extend(['-machine', machine])

  if use_kvm:
    qemu_cmd.extend(['-enable-kvm', '-cpu', 'host'])
  elif arch == 'aarch64':
    qemu_cmd.extend(['-machine', 'virtualization=true', '-cpu', 'cortex-a53'])
  elif arch == 'x86_64':
    qemu_cmd.extend(['-cpu', 'Haswell,+smap,-check,-fsgsbase'])

  if blkdev:
    qemu_cmd.extend([
      '-drive', 'file=%s,format=raw,if=none,id=testdisk' % blkdev,
      '-device', 'virtio-blk-pci,drive=testdisk,addr=%s' % TEST_FS_PCI_ADDR,
    ])

  return qemu_cmd


def TriggerTestsTask(api, name, cmd, arch, use_kvm, isolated_hash, output='',
                     timeout_secs=60*60):
  """TriggerTestsTask triggers a task to execute a command on a remote machine.

  The remote machine is guaranteed to have QEMU installed

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
    qemu_cipd_arch = 'amd64'
  else:
    qemu_cipd_arch = {
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
    return api.swarming.trigger(
        name,
        cmd,
        isolated=isolated_hash,
        dimensions=dimensions,
        hard_timeout=timeout_secs,
        io_timeout=TEST_IO_TIMEOUT_SECS,
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
        outputs=[output] if output else None,
    ).json.output['TaskID']


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

  # Analyze core tests results. We don't try to analyze further because we don't
  # have the core tests output in an easily consumable form, so they act as sort
  # of a smoke test.
  api.fuchsia.analyze_collect_result(
      'core tests task results',
      results_map[core_task],
      build_dir,
  )

  # Analyze booted tests results just like the fuchsia recipe module does.
  booted_result = results_map[booted_task]
  api.fuchsia.analyze_collect_result(
      'booted tests task results',
      booted_result,
      build_dir,
  )

  # Extract test results from the MinFS image.
  test_results_dir = api.path['start_dir'].join('test_results')
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
        output=booted_result.output,
        outputs=test_results_map,
  ))


def Build(api, target, toolchain, src_dir, needs_blkdev):
  """Builds zircon and returns a path to the build output directory."""
  # Generate runcmds script to drive tests.
  tmp_dir = api.path['cleanup'].join('zircon_tmp')
  api.file.ensure_directory('makedirs tmp', tmp_dir)
  runcmds_path = tmp_dir.join('runcmds')
  # In the use_isolate case, we need to mount a block device to write test
  # results and test output to. Thus, the runcmds script must:
  target_test_dir = api.fuchsia.target_test_dir()
  runcmds = [
    '#!/boot/bin/sh',
    # 1. Make a test directory.
    'mkdir %s' % target_test_dir,
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
      'mount %s %s' % (device_topological_path, target_test_dir),
      # 4. Execute runtests with -o (i.e. write test output to files with a
      # JSON summary).
      'runtests -o %s' % target_test_dir,
      # 5. Unmount and poweroff.
      'umount %s' % target_test_dir,
      'dm poweroff',
    ])
  else:
    # If we don't need a block device, just run the tests and wait for
    # something to copy the test results off. Note that in this case we do not
    # power off the device (via `dm poweroff`).
    runcmds.extend([
      # 2. Execute runtests with -o (i.e. write test output to files with a
      # JSON summary).
      'runtests -o %s' % target_test_dir,
    ])
  api.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
  api.step.active_result.presentation.logs['runcmds.sh'] = runcmds

  with api.step.nest('build'):
    # Set up toolchain and build args.
    tc_args, tc_suffix = TOOLCHAINS[toolchain]
    build_args = [
      'make',
      target,
      'HOST_USE_ASAN=true',
    ] + tc_args

    # Set up goma.
    if toolchain in ['clang', 'asan']:
      build_args.extend([
        'GOMACC=%s' % api.goma.goma_dir.join('gomacc'),
        '-j', api.goma.recommended_goma_jobs,
      ])
      goma_context = api.goma.build_with_goma
    else:
      build_args.extend([
        '-j', api.platform.cpu_count,
      ])
      goma_context = no_goma

    # If thinlto build, it needs a cache. Pass it a directory in the cache
    # directory.
    if toolchain == 'thinlto':
      build_args.append('THINLTO_CACHE_DIR=' +
                        str(api.path['cache'].join('thinlto')))

    # Declares a runcmds as a dependency for the build image, so it will get
    # copied into the image at RUNCMDS_BOOTFS_PATH.
    #
    # The bootfs manifest is a list of mappings between bootfs paths and local
    # file paths. The syntax is roughly:
    # install/path/under/boot=path/to/file/or/dir.
    runcmds_manifest = '%s=%s' % (RUNCMDS_BOOTFS_PATH, runcmds_path)

    # Build zircon.
    with goma_context():
      # Set EXTRA_USER_MANIFEST_LINES, which adds runcmds_manifest to the bootfs
      # manifest, ultimately propagating runcmds into the image.
      env = {'EXTRA_USER_MANIFEST_LINES': runcmds_manifest}
      with api.context(cwd=src_dir, env=env):
        api.step('build', build_args)

  # Return the location of the build artifacts.
  return src_dir.join('build-%s' % target + tc_suffix)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target, toolchain, goma_dir, use_kvm, run_tests, device_type):
  if goma_dir:
    api.goma.set_goma_dir(goma_dir)
  api.goma.ensure_goma()
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    if patch_ref:
      api.jiri.update(gc=True, rebase_tracked=True, local_manifest=True)

  src_dir = api.path['start_dir'].join('zircon')
  build_dir = Build(
      api=api,
      target=target,
      toolchain=toolchain,
      src_dir=src_dir,
      needs_blkdev=(device_type == 'QEMU'),
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
  collect_data = api.step_data('collect', api.swarming.collect(
      task_ids=['10', '11'],
      outputs=['output.fs'],
  ))
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
  yield (api.test('ci_x86') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
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
  yield (api.test('ci_device') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc',
                     device_type='Intel NUC Kit NUC6i3SYK') +
      booted_tests_trigger_data +
      api.step_data('collect', api.swarming.collect(
          outputs=['out.tar'],
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
          task_ids=['10', '11'],
          task_failure=True,
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
  yield (api.test('goma_dir') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x64',
                     toolchain='gcc',
                     goma_dir='/path/to/goma') +
      core_tests_trigger_data +
      booted_tests_trigger_data +
      collect_data)
