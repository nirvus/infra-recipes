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
  'infra/isolate',
  'infra/jiri',
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

TEST_RUNNER_PORT = 8342

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
  'modules': Property(kind=List(basestring), help='Packages to build',
                      default=['build/gn/default']),
  'tests': Property(kind=str,
                    help='Path to config file listing tests to run, or (when using autorun) command to run tests',
                    default=None),
  'use_autorun': Property(kind=bool,
                          help='Whether to use autorun for tests',
                          default=True),
  'use_isolate': Property(kind=bool,
                          help='Whether to run tests on another machine',
                          default=False),
  'goma_dir': Property(kind=str, help='Path to goma', default=None),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
}


def Checkout(api, patch_project, patch_ref, patch_gerrit_url, project, manifest,
             remote):
  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    if manifest in ['garnet', 'peridot']:
      revision = api.jiri.project([manifest]).json.output[0]['revision']
      api.step.active_result.presentation.properties['got_revision'] = revision
    if patch_ref:
      api.jiri.update(gc=True, rebase_tracked=True, local_manifest=True)
    if not api.properties.get('tryjob', False):
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


def BuildFuchsia(api, build_type, target, gn_target, fuchsia_build_dir,
                 modules, tests, use_autorun, use_isolate, gn_args):
  autorun_path = None
  if tests:
    if use_autorun or use_isolate:
      autorun = {
        True:  ['msleep 500', tests, 'msleep 15000', 'dm poweroff'],
        False: ['msleep 500', tests, 'echo "%s"' % TEST_SHUTDOWN],
      }[use_isolate]
      autorun_path = api.path['tmp_base'].join('autorun')
      api.file.write_text('write autorun', autorun_path, '\n'.join(autorun))
      api.step.active_result.presentation.logs['autorun.sh'] = autorun
    else:
      modules.append('build/gn/boot_test_runner')

  goma_env = {}
  if api.properties.get('goma_local_cache', False):
    goma_env['GOMA_LOCAL_OUTPUT_CACHE_DIR'] = api.path['cache'].join('goma', 'localoutputcache')

  with api.step.nest('build fuchsia'):
    with api.goma.build_with_goma(env=goma_env):
      gen_cmd = [
        api.path['start_dir'].join('build', 'gn', 'gen.py'),
        '--target_cpu=%s' % gn_target,
        '--packages=%s' % ','.join(modules),
      ]

      if autorun_path:
        gen_cmd.append('--autorun=%s' % autorun_path)

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
  zircon_image_name = {
    'arm64': 'zircon.elf',
    'x86-64': 'zircon.bin',
  }[target]

  # Copy the images to CWD so that when we later download the artifacts appear
  # in CWD. This eliminates having to do any arcane path logic later.
  api.file.copy('copy zircon image', zircon_build_dir.join(zircon_image_name), api.path['start_dir'])
  api.file.copy('copy fs image', fuchsia_build_dir.join('user.bootfs'), api.path['start_dir'])

  # Hack that creates an isolate file suitable for consumption by the client.
  #
  # TODO(mknyszek): Replace this with new interface once the isolate recipe
  # module is updated to use the golang isolated client.
  isolate_str = str(api.json.dumps({
    'variables': {
      'files': [
        os.path.relpath(str(api.path['start_dir'].join(zircon_image_name)), str(api.path['start_dir'])),
        os.path.relpath(str(api.path['start_dir'].join('user.bootfs')), str(api.path['start_dir'])),
      ]
    }
  }))
  isolate_path = api.path.join(api.path['start_dir'], 'result.isolate')
  api.file.write_text('write isolate', isolate_path, isolate_str.replace('"', '\''))

  # Archive, then extract and return digest for isolated.
  isolated_path = api.path['tmp_base'].join('result.isolated')
  return api.isolate.archive(isolate_path, isolated_path)['result']


def RunTestsInTask(api, target, isolated_hash):
  zircon_image_name = {
    'arm64': 'zircon.elf',
    'x86-64': 'zircon.bin',
  }[target]

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

  qemu_cmd = [
    './qemu/bin/qemu-system-' + qemu_arch, # Dropped in by CIPD.
    '-m', '4096',
    '-smp', '4',
    '-nographic',
    '-machine', {'aarch64': 'virt', 'x86_64': 'q35'}[qemu_arch],
    '-kernel', zircon_image_name,
    '-serial', 'stdio',
    '-monitor', 'none',
    '-initrd', 'user.bootfs',
    '-enable-kvm', '-cpu', 'host',
  ]

  qemu_cipd_arch = {
    'arm64': 'arm64',
    'x86-64': 'amd64',
  }[target]

  with api.context(infra_steps=True):
    # Trigger task.
    trigger_result = api.swarming.trigger(
        'trigger tests',
        qemu_cmd,
        isolated=isolated_hash,
        dump_json=api.path.join(api.path['tmp_base'], 'qemu_test_results.json'),
        dimensions={
          'pool': 'luci.fuchsia.ci',
          'os':   'Debian',
          'cpu':  target,
          'kvm':  '1',
        },
        io_timeout=60,
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
    )
  # Collect results. This is not listed as an infra step because we want the
  # results to be not infra steps. The collect operation itself is always an
  # infra step.
  api.swarming.collect('20m', requests_json=api.json.input(trigger_result.json.output))


def RunTestsWithTCP(api, target, fuchsia_build_dir, tests):
  zircon_build_dir = {
    'arm64': 'build-zircon-qemu-arm64',
    'x86-64': 'build-zircon-pc-x86-64',
  }[target]

  zircon_image_name = {
    'arm64': 'zircon.elf',
    'x86-64': 'zircon.bin',
  }[target]

  zircon_image_path = api.path['start_dir'].join(
    'out', 'build-zircon', zircon_build_dir, zircon_image_name)

  bootfs_path = fuchsia_build_dir.join('user.bootfs')

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

  netdev = 'user,id=net0,hostfwd=tcp::%d-:%d' % (
      TEST_RUNNER_PORT, TEST_RUNNER_PORT)

  qemu = api.qemu.background_run(
      qemu_arch,
      zircon_image_path,
      kvm=True,
      memory=4096,
      initrd=bootfs_path,
      netdev=netdev,
      devices=['e1000,netdev=net0'])

  with qemu:
    run_tests_cmd = [
      api.path['start_dir'].join('garnet', 'bin', 'test_runner', 'run_test'),
      '--test_file', api.path['start_dir'].join(tests),
      '--server', '127.0.0.1',
      '--port', str(TEST_RUNNER_PORT),
    ]
    try:
      api.step('run tests', run_tests_cmd)
    finally:
      # Give time for output to get flushed before reading the QEMU log.
      # TODO(bgoldman): Capture diagnostic information like FTL_LOG and
      # backtraces synchronously.
      api.step('sleep', ['sleep', '3'])

      symbolize_cmd = [
        api.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
        '--no-echo',
        '--file', 'qemu.stdout',
        '--build-dir', fuchsia_build_dir,
      ]
      step_result = api.step('symbolize', symbolize_cmd,
          stdout=api.raw_io.output(),
          step_test_data=lambda: api.raw_io.test_api.stream_output(''))

      lines = step_result.stdout.splitlines()
      if lines:
        # If symbolize found any backtraces in qemu.stdout, mark the symbolize
        # step as failed to indicate that it should be looked at.
        step_result.presentation.logs['symbolized backtraces'] = lines
        step_result.presentation.status = api.step.FAILURE


def RunTestsWithAutorun(api, target, fuchsia_build_dir):
  zircon_build_dir = {
    'arm64': 'build-zircon-qemu-arm64',
    'x86-64': 'build-zircon-pc-x86-64',
  }[target]

  zircon_image_name = {
    'arm64': 'zircon.elf',
    'x86-64': 'zircon.bin',
  }[target]

  zircon_image_path = api.path['start_dir'].join(
    'out', 'build-zircon', zircon_build_dir, zircon_image_name)

  bootfs_path = fuchsia_build_dir.join('user.bootfs')

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

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
    symbolize_cmd = [
      api.path['start_dir'].join('zircon', 'scripts', 'symbolize'),
      '--no-echo',
      '--build-dir', fuchsia_build_dir,
    ]
    symbolize_result = api.step('symbolize', symbolize_cmd,
        stdin=api.raw_io.input(data=qemu_log),
        stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(''))
    symbolized_lines = symbolize_result.stdout.splitlines()
    if symbolized_lines:
      symbolize_result.presentation.logs['symbolized backtraces'] = symbolized_lines
      symbolize_result.presentation.status = api.step.FAILURE

    raise api.step.StepFailure(failure_reason)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target, build_type, modules, tests, use_autorun, use_isolate,
             goma_dir, gn_args):
  # Tests are too slow on arm64.
  if target == 'arm64':
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
      api.isolate.ensure_isolate(version='latest')
    else:
      api.qemu.ensure_qemu()

  Checkout(api, patch_project, patch_ref, patch_gerrit_url, project, manifest,
           remote)

  BuildZircon(api, zircon_project)
  BuildFuchsia(api, build_type, target, gn_target, fuchsia_build_dir,
               modules, tests, use_autorun, use_isolate, gn_args)

  if tests:
    if use_isolate:
      isolated = IsolateArtifacts(api, target, zircon_build_dir, fuchsia_build_dir)
      RunTestsInTask(api, target, isolated)
    elif use_autorun:
      RunTestsWithAutorun(api, target, fuchsia_build_dir)
    else:
      RunTestsWithTCP(api, target, fuchsia_build_dir, tests)


def GenTests(api):
  # Test cases for running Fuchsia tests over TCP.
  yield api.test('tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='tests.json',
      use_autorun=False,
  )
  yield api.test('failed_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='tests.json',
      use_autorun=False,
  ) + api.step_data('run tests', retcode=1)
  yield api.test('backtrace') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='tests.json',
      use_autorun=False,
  ) + api.step_data('run tests', retcode=1,
  ) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))

  # Test cases for running Fuchsia tests with autorun.
  yield api.test('autorun_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed\n' + TEST_SHUTDOWN))
  yield api.test('autorun_failed_qemu') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
  ) + api.step_data('run tests', retcode=1)
  yield api.test('autorun_no_results') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output(TEST_SHUTDOWN))
  yield api.test('autorun_tests_timeout') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
  ) + api.step_data('run tests', retcode=2)
  yield api.test('autorun_failed_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 1 failed\n' + TEST_SHUTDOWN))
  yield api.test('autorun_backtrace') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 1 failed'),
  ) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))

  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result())
  yield api.test('isolated_tests_task_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(task_failure=True))
  yield api.test('isolated_tests_infra_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='runtests',
      use_isolate=True,
  ) + api.step_data('collect', api.swarming.collect_result(infra_failure=True))

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      autorun=False,
  )
  yield api.test('garnet') + api.properties(
      project='garnet',
      manifest='manifest/garnet',
      remote='https://fuchsia.googlesource.com/garnet',
      target='x86-64',
      autorun=False,
  )
  yield api.test('peridot') + api.properties(
      manifest='peridot',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      autorun=False,
  )
  yield api.test('no_goma') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      goma_dir='/path/to/goma',
      autorun=False,
  )
  yield api.test('goma_local_cache') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      goma_local_cache=True,
      autorun=False,
  )
  yield api.test('arm64_skip_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      tests='tests.json',
      autorun=False,
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='release',
      autorun=False,
  )
  yield api.test('lto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='lto',
      autorun=False,
  )
  yield api.test('thinlto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='thinlto',
      autorun=False,
  )
  yield api.test('cq') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      autorun=False,
      tryjob=True,
  )
  yield api.test('gn_args') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tryjob=True,
      autorun=False,
      gn_args=['super_arg=false', 'less_super_arg=true'],
  )
  yield api.test('manifest') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_project='manifest',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      autorun=False,
      tryjob=True,
  )
