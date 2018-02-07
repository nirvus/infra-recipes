# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Zircon."""

import contextlib
import re

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property, StepFailure


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/jiri',
  'infra/isolated',
  'infra/minfs',
  'infra/qemu',
  'infra/swarming',
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

TARGETS = ['x86', 'arm64', 'hikey960', 'gauss', 'odroidc2']
TARGET_TO_ARCH = dict(zip(
    TARGETS,
    ['x86_64', 'aarch64', 'aarch64', 'aarch64', 'aarch64'],
))

# toolchain: (['make', 'args'], 'builddir-suffix')
TOOLCHAINS = {
  'gcc': ([], ''),
  'clang': (['USE_CLANG=true'], '-clang'),
  'asan': (['USE_ASAN=true'], '-asan'),
  'lto': (['USE_LTO=true', 'USE_THINLTO=false'], '-lto'),
  'thinlto': (['USE_LTO=true', 'USE_THINLTO=true'], '-thinlto'),
}

# Test summary from the core tests, which run directly from userboot.
CORE_TESTS_MATCH = r'CASES: +(\d+) +SUCCESS: +(\d+) +FAILED: +(?P<failed>\d+)'

# Test summary from the runtests command on a booted system.
BOOTED_TESTS_MATCH = r'SUMMARY: Ran (\d+) tests: (?P<failed>\d+) failed'

# The kernel binary to pass to qemu.
ZIRCON_IMAGE_NAME = 'zircon.bin'

# The boot filesystem image.
BOOTFS_IMAGE_NAME = 'bootdata.bin'

# The PCI address to use for the block device to contain test results. This value
# is somewhat arbitrary, but it works very consistently and appears to be a safe
# PCI address value to use within QEMU.
TEST_FS_PCI_ADDR = '06.0'

# How long to wait (in seconds) before killing the test swarming task if there's
# no output being produced.
TEST_IO_TIMEOUT_SECS = 60

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
  'use_isolate': Property(kind=bool,
                          help='Whether to run tests on another machine',
                          default=False),
}


@contextlib.contextmanager
def no_goma():
    yield


def RunTests(api, name, build_dir, *args, **kwargs):
  step_result = None
  failure_reason = None
  try:
    step_result = api.qemu.run(name, *args, **kwargs)
  except StepFailure as error:
    step_result = error.result
    if error.retcode == 2:
      failure_reason = 'Test timed out'
    else:
      raise api.step.InfraFailure('QEMU failure')

  qemu_log = step_result.stdout
  step_result.presentation.logs['qemu.stdout'] = qemu_log.splitlines()

  if failure_reason is None:
    m = re.search(kwargs['shutdown_pattern'], qemu_log)
    if not m:
      raise api.step.InfraFailure('Test output missing')
    elif int(m.group('failed')) > 0:
      step_result.presentation.status = api.step.FAILURE
      failure_reason = m.group(0)

  if failure_reason is not None:
    symbolize_cmd = [
      api.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
      '--no-echo',
      '--build-dir', build_dir,
    ]
    symbolize_result = api.step('symbolize', symbolize_cmd,
        stdin=api.raw_io.input(data=qemu_log),
        stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized backtrace'] = symbolized_lines
      symbolize_result.presentation.status = api.step.FAILURE

    raise api.step.StepFailure(failure_reason)


def TriggerTestsTask(api, name, arch, isolated_hash, cmdline, blkdev=False):
  """TriggerTestsTask triggers a task to execute Zircon tests within QEMU.

  Args:
    api: Recipe engine API object.
    name (str): Name of the task.
    arch (str): The target architecture to execute tests for.
    isolated_hash (str): A digest of the isolated containing the build
      artifacts.
    cmdline (list[str]): A list of kernel command line arguments to pass to
      zircon.
    blkdev (bool): Whether a block device should be declared.

  Returns:
    The task ID of the triggered task.
  """
  qemu_cmd = [
    './qemu/bin/qemu-system-' + arch, # Dropped in by CIPD.
    '-m', '4096',
    '-smp', '4',
    '-nographic',
    '-machine', {'aarch64': 'virt,gic_version=host', 'x86_64': 'q35'}[arch],
    '-kernel', ZIRCON_IMAGE_NAME,
    '-serial', 'stdio',
    '-monitor', 'none',
    '-initrd', BOOTFS_IMAGE_NAME,
    '-enable-kvm', '-cpu', 'host',
    '-append', ' '.join(['TERM=dumb', 'kernel.halt-on-panic=true'] + cmdline),
  ]

  if blkdev:
    qemu_cmd.extend([
      '-drive', 'file=test.fs,format=raw,if=none,id=testdisk',
      '-device', 'virtio-blk-pci,drive=testdisk,addr=%s' % TEST_FS_PCI_ADDR,
    ])

  qemu_cipd_arch = {
    'aarch64': 'arm64',
    'x86_64': 'amd64',
  }[arch]

  with api.context(infra_steps=True):
    # Trigger task.
    return api.swarming.trigger(
        name,
        qemu_cmd,
        isolated=isolated_hash,
        dump_json=api.path.join(api.path['tmp_base'], 'qemu_test_results.json'),
        dimensions={
          'pool': 'fuchsia.tests',
          'os':   'Debian',
          'cpu':  {'aarch64': 'arm64', 'x86_64': 'x86-64'}[arch],
          'kvm':  '1',
        },
        io_timeout=TEST_IO_TIMEOUT_SECS,
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
    ).json.output['TaskID']


def CollectTestsTasks(api, tasks, timeout='20m'):
  """Waits on a set of swarming tasks.

  Args:
    tasks (list[str]): A list of swarming task IDs to wait on.
    timeout (str): A timeout formatted as a Golang Duration-parsable string.
  """
  with api.context(infra_steps=True):
    collects = api.swarming.collect(timeout, tasks=tasks)
    assert len(collects) == len(tasks)
  for result in collects:
    if result.is_failure() or result.is_infra_failure():
      raise api.step.InfraFailure('failed to collect results: %s' % result.output)


def Build(api, target, toolchain, src_dir, use_isolate):
  """Builds zircon and returns a path to the build output directory."""
  # Generate autorun script to drive tests.
  tmp_dir = api.path['tmp_base'].join('zircon_tmp')
  api.file.ensure_directory('makedirs tmp', tmp_dir)
  autorun_path = tmp_dir.join('autorun')
  if use_isolate:
    # In the use_isolate case, we need to mount a block device to write test
    # results and test output to. Thus, the autorun script must:
    # 1. Wait for devmgr to spin up.
    # 2. Make a test directory.
    # 3. Mount the block device to that test directory (the block device
    #    will always exist at PCI address TEST_FS_PCI_ADDR).
    # 4. Execute runtests with -o.
    # 5. Unmount and poweroff.
    autorun = [
      'msleep 1000',
      'mkdir /test',
      'mount /dev/sys/pci/00:%s/virtio-block/block' % TEST_FS_PCI_ADDR,
      'runtests -o /test',
      'umount /test',
      'dm poweroff',
    ]
  else:
    # Script to wait for devmgr to spin up and execute runtests. runtests doesn't
    # need any additional arguments because it executes tests in five /boot
    # directories by default, representing the entire test suite.
    autorun = ['msleep 500', 'runtests']
  api.file.write_text('write autorun', autorun_path, '\n'.join(autorun))
  api.step.active_result.presentation.logs['autorun.sh'] = autorun

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

    # Build zircon.
    with goma_context():
      with api.context(cwd=src_dir, env={'USER_AUTORUN': autorun_path}):
        api.step('build', build_args)

  # Return the location of the build artifacts.
  return src_dir.join('build-%s' % target + tc_suffix)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target, toolchain, goma_dir, use_isolate, run_tests):
  if goma_dir:
    api.goma.set_goma_dir(goma_dir)
  api.goma.ensure_goma()
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    revision = api.jiri.project(['zircon']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision
    if patch_ref:
      api.jiri.update(gc=True, rebase_tracked=True, local_manifest=True)

  src_dir = api.path['start_dir'].join('zircon')
  build_dir = Build(api, target, toolchain, src_dir, use_isolate)

  if run_tests:
    api.qemu.ensure_qemu()
    if use_isolate:
      api.swarming.ensure_swarming(version='latest')
      api.isolated.ensure_isolated(version='latest')

    bootfs_path = build_dir.join(BOOTFS_IMAGE_NAME)
    image_path = build_dir.join(ZIRCON_IMAGE_NAME)

    # The MinFS tool is generated during the Zircon build, so only after we
    # build may we set the recipe module's tool path.
    api.minfs.minfs_path = build_dir.join('tools', 'minfs')

    arch = TARGET_TO_ARCH[target]
    if use_isolate:
      # Generate a MinFS image which will hold test results. This will later be
      # declared as a block device to QEMU and will then be mounted by the
      # autorun script. The size of the MinFS should be large enough to
      # accomodate all test results and test output. The current size is picked
      # to be able to safely hold test results for quite some time (currently
      # the space used is on the order of tens of kilobytes). Having a
      # larger-image-than-necessary isn't a big deal for isolate, which
      # compresses the image before uploading.
      test_image = api.path['start_dir'].join('test.fs')
      api.minfs.create(test_image, '32M', name='create test image')

      # Isolate all necessary build artifacts as well as the MinFS image.
      isolated = api.isolated.isolated()
      isolated.add_file(test_image, wd=api.path['start_dir'])
      isolated.add_file(image_path, wd=build_dir)
      isolated.add_file(bootfs_path, wd=build_dir)
      digest = isolated.archive('isolate %s and %s' % (ZIRCON_IMAGE_NAME, BOOTFS_IMAGE_NAME))

      tasks = [
        # Trigger a task that runs the core tests in place of userspace at boot.
        TriggerTestsTask(api, 'core tests', arch, digest, [
          'userboot=bin/core-tests',
          'userboot.shutdown', # shuts down zircon after the userboot process exits.
        ]),
        # Trigger a task that runs tests in the standard way with runtests and
        # the autorun script.
        TriggerTestsTask(api, 'booted tests', arch, digest, [], blkdev=True),
      ]
      CollectTestsTasks(api, tasks, timeout='20m')
    else:
      # Run core tests with userboot.
      RunTests(api, 'run core tests', build_dir, arch, image_path, kvm=True,
          initrd=bootfs_path, cmdline='userboot=bin/core-tests',
          shutdown_pattern=CORE_TESTS_MATCH, timeout=300, step_test_data=lambda:
              api.raw_io.test_api.stream_output('CASES: 1 SUCCESS: 1 FAILED: 0'))

      # Boot and run tests.
      RunTests(api, 'run booted tests', build_dir, arch, image_path, kvm=True,
          initrd=bootfs_path, shutdown_pattern=BOOTED_TESTS_MATCH, timeout=1200,
          step_test_data=lambda:
              api.raw_io.test_api.stream_output('SUMMARY: Ran 2 tests: 1 failed'))


def GenTests(api):
  yield (api.test('ci') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x86',
                    toolchain='gcc') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('asan') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x86',
                    toolchain='asan') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('lto') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x86',
                    toolchain='lto') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('thinlto') +
     api.properties(project='zircon',
                    manifest='manifest',
                    remote='https://fuchsia.googlesource.com/zircon',
                    target='x86',
                    toolchain='thinlto') +
     api.step_data('run booted tests',
         api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed')))
  yield (api.test('cq_try') +
     api.properties.tryserver(
         gerrit_project='zircon',
         patch_gerrit_url='fuchsia-review.googlesource.com',
         project='zircon',
         manifest='manifest',
         remote='https://fuchsia.googlesource.com/zircon',
         target='x86',
         toolchain='clang'))
  yield (api.test('no_run_tests') +
     api.properties.tryserver(
         project='zircon',
         manifest='manifest',
         remote='https://fuchsia.googlesource.com/zircon',
         target='x86',
         toolchain='clang',
         run_tests=False))
  yield (api.test('failed_qemu') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc') +
      api.step_data('run booted tests', retcode=1))
  yield (api.test('qemu_timeout') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc') +
      api.step_data('run booted tests', retcode=2))
  yield (api.test('test_ouput') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc') +
      api.step_data('run booted tests', api.raw_io.stream_output('')))
  yield (api.test('goma_dir') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc',
                     goma_dir='/path/to/goma') +
      api.step_data('run booted tests', api.raw_io.stream_output('')))
  yield (api.test('use_isolate') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc',
                     use_isolate=True) +
      api.step_data('collect', api.swarming.collect(task_ids=['10', '11'])))
  yield (api.test('use_isolate_failure') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc',
                     use_isolate=True) +
      api.step_data('collect', api.swarming.collect(
          task_ids=['10', '11'],
          task_failure=True,
      )))
  yield (api.test('symbolized_output') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc') +
      api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n')))
