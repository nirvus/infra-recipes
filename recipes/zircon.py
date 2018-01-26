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

# The manifest which describes what goes into the boot filesystem image.
BOOTFS_MANIFEST_NAME = 'bootfs.manifest'

# The boot filesystem image.
BOOTFS_IMAGE_NAME = 'bootdata.bin'

# The path under /boot to the runcmds script (which runs tests) in the zircon
# bootfs.
RUNCMDS_BOOTFS_PATH = 'infra/runcmds'

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


def TriggerTestsTask(api, name, arch, isolated_hash, cmdline):
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
        io_timeout=60,
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
    ).json.output['TaskID']


def CollectTestsTasks(api, tasks, timeout='20m'):
  with api.context(infra_steps=True):
    collect_results = api.swarming.collect(timeout, tasks=tasks)
    assert len(collect_results) == len(tasks)
  for result in collect_results:
    if result.is_failure() or result.is_infra_failure():
      raise api.step.InfraFailure('failed to collect results: %s' % result.output)


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

  with api.step.nest('build'):
    src_dir = api.path['start_dir'].join('zircon')

    # Set up totolchain and build args.
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
      with api.context(cwd=src_dir):
        api.step('build', build_args)

    # Generate runcmds script to drive tests.
    tmp_dir = api.path['tmp_base'].join('zircon_tmp')
    api.file.ensure_directory('makedirs tmp', tmp_dir)
    runcmds_path = tmp_dir.join('runcmds')
    runcmds = ['#!/boot/bin/sh', 'msleep 500', 'runtests']
    # In the non-use_isolate case, we don't need this because the QEMU recipe
    # module forcefully kills QEMU when encountering the shutdown pattern.
    # In a swarming task, this is impossible because 1) although we can cancel a
    # swarming task we won't get any useful feedback on whether it was successful
    # without grepping through the output and 2) we would need a way to stream the
    # output into a recipe, which currently can't be done easily.
    #
    # So, we gracefully shutdown zircon after running tests.
    if use_isolate:
      runcmds.append('dm poweroff')
    api.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
    api.step.active_result.presentation.logs['runcmds'] = runcmds

    build_dir = src_dir.join('build-%s' % target + tc_suffix)

    # Add the runcmds script to the bootfs manifest.
    #
    # The bootfs manifest is a list of mappings between bootfs paths and local
    # file paths. The syntax is roughly:
    # {optional-tag}install/path/under/boot=path/to/file/or/dir.

    # Read the lines of the bootfs manifest.
    manifest_lines = api.file.read_text(
        'read bootfs manifest',
        build_dir.join(BOOTFS_MANIFEST_NAME),
    ).split('\n')

    # Append a new line for runcmds. {test} is a tag marking that a file is
    # related to testing. It doesn't serve any purpose besides aesthetics.
    manifest_lines.append('{test}%s=%s' % (RUNCMDS_BOOTFS_PATH, runcmds_path))

    # Write the new bootfs manifest.
    test_bootfs_manifest_path = src_dir.join('test.manifest')
    api.file.write_text(
        'write bootfs manifest',
        test_bootfs_manifest_path,
        '\n'.join(manifest_lines),
    )

    # Re-generate the bootfs image with make. Must be in the context of the
    # src_dir because many of the paths in bootfs.manifest are relative.
    with api.context(cwd=src_dir):
      api.step('make bootfs', [
        build_dir.join('tools', 'mkbootfs'),
        '--target=boot',
        '-c',
        '-o', build_dir.join(BOOTFS_IMAGE_NAME),
        test_bootfs_manifest_path,
      ])

  if run_tests:
    autorun_arg = 'zircon.autorun.boot=/boot/' + RUNCMDS_BOOTFS_PATH
    api.qemu.ensure_qemu()
    if use_isolate:
      api.swarming.ensure_swarming(version='latest')
      api.isolated.ensure_isolated(version='latest')

    bootfs_path = build_dir.join(BOOTFS_IMAGE_NAME)
    image_path = build_dir.join(ZIRCON_IMAGE_NAME)

    arch = TARGET_TO_ARCH[target]
    if use_isolate:
      isolated = api.isolated.isolated()
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
        TriggerTestsTask(api, 'booted tests', arch, digest, [autorun_arg]),
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
          initrd=bootfs_path, cmdline=autorun_arg,
          shutdown_pattern=BOOTED_TESTS_MATCH, timeout=1200, step_test_data=lambda:
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
      api.step_data('collect', api.swarming.collect_result(amount=2)))
  yield (api.test('use_isolate_failure') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc',
                     use_isolate=True) +
      api.step_data('collect', api.swarming.collect_result(amount=2, task_failure=True)))
  yield (api.test('symbolized_output') +
      api.properties(project='zircon',
                     manifest='manifest',
                     remote='https://fuchsia.googlesource.com/zircon',
                     target='x86',
                     toolchain='gcc') +
      api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n')))
