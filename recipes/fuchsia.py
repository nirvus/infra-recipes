# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import hashlib
import os
import re


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/gsutil',
  'infra/hash',
  'infra/isolated',
  'infra/jiri',
  'infra/minfs',
  'infra/qemu',
  'infra/swarming',
  'infra/tar',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/source_manifest',
  'recipe_engine/step',
]

TARGETS = ['arm64', 'x86-64']

TEST_SUMMARY = r'SUMMARY: Ran (\d+) tests: (?P<failed>\d+) failed'

TEST_SHUTDOWN = 'ready for fuchsia shutdown'

# The kernel binary to pass to qemu.
ZIRCON_IMAGE_NAME = 'zircon.bin'

# The boot filesystem image.
BOOTFS_IMAGE_NAME = 'user.bootfs'

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
  'build_type': Property(kind=Enum('debug', 'release', 'thinlto', 'lto'),
                         help='The build type', default='debug'),
  'packages': Property(kind=List(basestring), help='Packages to build',
                       default=[]),
  'variant': Property(kind=List(basestring),
                      help='--variant arguments to gen.py', default=[]),
  'tests': Property(kind=str,
                    help='Path to config file listing tests to run, or (when using autorun) command to run tests',
                    default=None),
  'use_isolate': Property(kind=bool,
                          help='Whether to run tests on another machine',
                          default=False),
  'upload_snapshot': Property(kind=bool,
                          help='Whether to upload jiri snapshot (always False if tryjob is true)',
                          default=True),
  'goma_dir': Property(kind=str, help='Path to goma', default=None),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
}


def Checkout(api, patch_project, patch_ref, patch_gerrit_url, project, manifest,
             remote, upload_snapshot):
  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    if patch_ref:
      api.jiri.update(gc=True, rebase_tracked=True, local_manifest=True)
    if upload_snapshot and not api.properties.get('tryjob', False):
      snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
      api.jiri.snapshot(snapshot_file)
      digest = api.hash.sha1('hash snapshot', snapshot_file,
                             test_data='8ac5404b688b34f2d34d1c8a648413aca30b7a97')
      api.gsutil.upload('fuchsia-snapshots', snapshot_file, digest,
          link_name='jiri.snapshot',
          name='upload jiri.snapshot',
          unauthenticated_url=True)


def BuildZircon(api, zircon_project):
  build_zircon_cmd = [
    api.path['start_dir'].join('scripts', 'build-zircon.sh'),
    '-c',
    '-H',
    '-p', zircon_project,
  ]
  api.step('build zircon', build_zircon_cmd)


def BuildFuchsia(api, build_type, target, gn_target, zircon_project,
                 fuchsia_build_dir, packages, variant, tests, use_isolate,
                 gn_args):
  if tests:
    runcmds = {
      True:  [
          '#!/boot/bin/sh',
          'msleep 5000',
          # TODO(mknyszek): Remove this ASAP. Auto-mount the image instead by
          # using minfs + fvm to create an image with a GPT and GUID 'DATA'.
          #
          # This will be a source of flake long-term as '000' will soon
          # frequently NOT be '000'.
          'mount /dev/class/block/000 /data',
          tests + ' > /data/tests.out',
          'msleep 10000',
          'dm poweroff',
      ],
      False: ['#!/boot/bin/sh', 'msleep 500', tests, 'echo "%s"' % TEST_SHUTDOWN],
    }[use_isolate]
    runcmds_path = api.path['tmp_base'].join('runcmds')
    api.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
    api.step.active_result.presentation.logs['runcmds'] = runcmds

    runcmds_package_path = api.path['tmp_base'].join('runcmds_package')
    runcmds_package = RUNCMDS_PACKAGE % runcmds_path
    api.file.write_text('write runcmds package', runcmds_package_path, runcmds_package)
    api.step.active_result.presentation.logs['runcmds_package'] = runcmds_package.splitlines()
    packages.append(str(runcmds_package_path))

  goma_env = {}
  if api.properties.get('goma_local_cache', False):
    goma_env['GOMA_LOCAL_OUTPUT_CACHE_DIR'] = api.path['cache'].join('goma', 'localoutputcache')

  with api.step.nest('build fuchsia'):
    with api.goma.build_with_goma(env=goma_env):
      gen_cmd = [
        api.path['start_dir'].join('build', 'gn', 'gen.py'),
        '--target_cpu=%s' % gn_target,
        '--packages=%s' % ','.join(packages),
        '--platforms=%s' % zircon_project,
      ]

      gen_cmd += ['--variant=%s' % v for v in variant]

      gen_cmd.append('--goma=%s' % api.goma.goma_dir)

      if build_type in ['release', 'lto', 'thinlto']:
        gen_cmd.append('--release')

      if build_type == 'lto':
        gen_cmd.append('--lto=full')
      elif build_type == 'thinlto':
        gen_cmd.append('--lto=thin')
        gn_args.append('thinlto_cache_dir=\"%s\"' %
                       str(api.path['cache'].join('thinlto')))

      for arg in gn_args:
        gen_cmd.append('--args')
        gen_cmd.append(arg)

      api.step('gen', gen_cmd)

      ninja_cmd = [
        api.path['start_dir'].join('buildtools', 'ninja'),
        '-C', fuchsia_build_dir,
      ]

      ninja_cmd.extend(['-j', api.goma.recommended_goma_jobs])

      api.step('ninja', ninja_cmd)


def IsolateArtifacts(api, target, zircon_build_dir, fuchsia_build_dir):
  test_image = api.path['start_dir'].join('test.fs')
  api.minfs.create(test_image, '32M', name='create test image')

  isolated = api.isolated.isolated()
  isolated.add_file(test_image, wd=api.path['start_dir'])
  isolated.add_file(zircon_build_dir.join(ZIRCON_IMAGE_NAME), wd=zircon_build_dir)
  isolated.add_file(fuchsia_build_dir.join(BOOTFS_IMAGE_NAME), wd=fuchsia_build_dir)
  return isolated.archive('isolate %s and %s' % (ZIRCON_IMAGE_NAME, BOOTFS_IMAGE_NAME))


def RunTestsInTask(api, target, isolated_hash, tests, fuchsia_build_dir):
  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

  cmdline = 'zircon.autorun.system=/system/data/infra/runcmds'

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
    '-append', cmdline,
    '-drive', 'file=test.fs,format=raw,if=none,id=mydisk',
    '-device', 'ahci,id=ahci',
    '-device', 'ide-drive,drive=mydisk,bus=ahci.0',
  ]

  qemu_cipd_arch = {
    'arm64': 'arm64',
    'x86-64': 'amd64',
  }[target]

  with api.context(infra_steps=True):
    # Trigger task.
    trigger_result = api.swarming.trigger(
        'all tests',
        qemu_cmd,
        isolated=isolated_hash,
        dump_json=api.path.join(api.path['tmp_base'], 'qemu_test_results.json'),
        dimensions={
          'pool': 'fuchsia.tests',
          'os':   'Debian',
          'cpu':  target,
          'kvm':  '1',
        },
        io_timeout=60,
        outputs=['test.fs'],
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
    )
    # Collect results.
    results = api.swarming.collect('20m', requests_json=api.json.input(trigger_result.json.output))
    assert len(results) == 1
    result = results[0]

  if result.is_infra_failure():
    raise api.step.InfraFailure('Failed to collect: %s' % result.output)
  elif result.is_failure():
    # If the kernel panics, chances are it will result in a task failure since
    # the task will likely time out and QEMU will be forcibly killed.
    if 'KERNEL PANIC' in result.output:
      Symbolize(api, fuchsia_build_dir, result.output)
      raise api.step.StepFailure('Found kernel panic. See symbolized output for details.')
    # If there's no kernel panic then it's likely an infra issue with QEMU,
    # though a deadlock might also reach this state.
    raise api.step.InfraFailure('Swarming task failed: %s' % result.output)

  # Copy test results out of image.
  test_results = api.minfs.cp(
      'tests.out',
      api.raw_io.output(leak_to=api.path['start_dir'].join('tests.out')),
      result['test.fs'],
      name='extract test results',
  )

  # Search output to see what happened.
  step_result = api.step('test results', None)
  test_results = test_results.raw_io.output
  step_result.presentation.logs['stdout'] = test_results.split('\n')
  match = re.search(TEST_SUMMARY, test_results)
  if not match:
    raise api.step.InfraFailure('Test output missing')
  elif int(match.group('failed')) > 0:
    Symbolize(api, fuchsia_build_dir, test_results)
    raise api.step.StepFailure(match.group(0))


def RunTestsWithAutorun(api, target, fuchsia_build_dir, tests):
  zircon_build_dir = {
    'arm64': 'build-zircon-qemu-arm64',
    'x86-64': 'build-zircon-pc-x86-64',
  }[target]

  zircon_image_path = api.path['start_dir'].join(
    'out', 'build-zircon', zircon_build_dir, ZIRCON_IMAGE_NAME)

  bootfs_path = fuchsia_build_dir.join(BOOTFS_IMAGE_NAME)

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

  cmdline = 'zircon.autorun.system=/system/data/infra/runcmds'

  run_tests_result = None
  failure_reason = None

  try:
    run_tests_result = api.qemu.run(
        'run tests',
        qemu_arch,
        zircon_image_path,
        kvm=True,
        memory=4096,
        initrd=bootfs_path,
        cmdline=cmdline,
        shutdown_pattern=TEST_SHUTDOWN)
  except api.step.StepFailure as error:
    run_tests_result = error.result
    if error.retcode == 2:
      failure_reason = 'Tests timed out'
    else:
      raise api.step.InfraFailure('QEMU failure')

  qemu_log = run_tests_result.stdout
  run_tests_result.presentation.logs['qemu log'] = qemu_log.splitlines()

  if failure_reason is None:
    m = re.search(TEST_SUMMARY, qemu_log)
    if not m:
      # This is an infrastructure failure because the TEST_SHUTDOWN string
      # should have been triggered to get to the this point, which means the
      # runtests command completed. runtests is supposed to output a string
      # matching TEST_SUMMARY.
      run_tests_result.presentation.status = api.step.EXCEPTION
      failure_reason = 'Test output missing'
    elif int(m.group('failed')) > 0:
      run_tests_result.presentation.status = api.step.FAILURE
      failure_reason = m.group(0)

  if failure_reason is not None:
    Symbolize(api, fuchsia_build_dir, qemu_log)
    raise api.step.StepFailure(failure_reason)


def Symbolize(api, build_dir, data):
    symbolize_cmd = [
      api.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
      '--no-echo',
      '--build-dir', build_dir,
    ]
    symbolize_result = api.step('symbolize', symbolize_cmd,
        stdin=api.raw_io.input(data=data),
        stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized backtraces'] = symbolized_lines
      symbolize_result.presentation.status = api.step.FAILURE


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target, build_type, packages, variant, tests, use_isolate,
             upload_snapshot, goma_dir, gn_args):
  # Tests are too slow on arm64.
  if target == 'arm64' and not use_isolate:
    tests = None

  gn_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]
  fuchsia_out_dir = api.path['start_dir'].join('out')
  if build_type in ['release', 'lto', 'thinlto']:
    build_dir = 'release'
  else:
    build_dir = 'debug'
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_dir, gn_target))

  zircon_project = {
    'arm64': 'zircon-qemu-arm64',
    'x86-64': 'zircon-pc-x86-64'
  }[target]
  zircon_build_dir = fuchsia_out_dir.join('build-zircon', 'build-%s' % zircon_project)

  if goma_dir:
    api.goma.set_goma_dir(goma_dir)

  api.jiri.ensure_jiri()
  api.gsutil.ensure_gsutil()
  api.goma.ensure_goma()
  if tests:
    if use_isolate:
      api.swarming.ensure_swarming(version='latest')
      api.isolated.ensure_isolated(version='latest')
    else:
      api.qemu.ensure_qemu()

  Checkout(api, patch_project, patch_ref, patch_gerrit_url, project, manifest,
           remote, upload_snapshot)

  BuildZircon(api, zircon_project)
  BuildFuchsia(api, build_type, target, gn_target, zircon_project,
               fuchsia_build_dir, packages, variant, tests, use_isolate, gn_args)

  if tests:
    if use_isolate:
      api.minfs.minfs_path = fuchsia_out_dir.join('build-zircon', 'tools', 'minfs')
      digest = IsolateArtifacts(api, target, zircon_build_dir, fuchsia_build_dir)
      RunTestsInTask(api, target, digest, tests, fuchsia_build_dir)
    else:
      RunTestsWithAutorun(api, target, fuchsia_build_dir, tests)


def GenTests(api):
  # Test cases for running Fuchsia tests with autorun.
  yield api.test('autorun_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed\n' + TEST_SHUTDOWN))
  yield api.test('autorun_failed_qemu') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
  ) + api.step_data('run tests', retcode=1)
  yield api.test('autorun_no_results') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output(TEST_SHUTDOWN))
  yield api.test('autorun_tests_timeout') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
  ) + api.step_data('run tests', retcode=2)
  yield api.test('autorun_failed_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 1 failed\n' + TEST_SHUTDOWN))
  yield api.test('autorun_backtrace') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 1 failed'),
  ) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))

  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(outputs=['test.fs']))
  yield api.test('isolated_tests_test_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  )) + api.step_data('extract test results', api.raw_io.output('SUMMARY: Ran 2 tests: 1 failed'))
  yield api.test('isolated_tests_task_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      task_failure=True,
  ))
  yield api.test('isolated_tests_kernel_panic') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      output='ZIRCON KERNEL PANIC',
      outputs=['test.fs'],
      task_failure=True,
  ))
  yield api.test('isolated_tests_infra_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      infra_failure=True,
  ))

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('garnet') + api.properties(
      project='garnet',
      manifest='manifest/garnet',
      remote='https://fuchsia.googlesource.com/garnet',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('peridot') + api.properties(
      manifest='peridot',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('no_goma') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      goma_dir='/path/to/goma',
  )
  yield api.test('goma_local_cache') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      goma_local_cache=True,
  )
  yield api.test('arm64_skip_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      packages=['topaz/packages/default'],
      tests='tests.json',
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      build_type='release',
  )
  yield api.test('lto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      build_type='lto',
  )
  yield api.test('thinlto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      build_type='thinlto',
  )
  yield api.test('host_asan') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      variant=['host_asan'],
  )
  yield api.test('asan') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      packages=['topaz/packages/default'],
      variant=['host_asan', 'asan'],
  )
  yield api.test('cq') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
  yield api.test('gn_args') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
      gn_args=['super_arg=false', 'less_super_arg=true'],
  )
  yield api.test('manifest') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_project='manifest',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
