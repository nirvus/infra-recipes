# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

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
  'run_tests': Property(kind=bool,
                        help='Whether to run tests or not',
                        default=False),
  'runtests_args': Property(kind=str,
                            help='Arguments to pass to the executable running tests',
                            default=''),
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
                 fuchsia_build_dir, packages, variant, run_tests, runtests_args,
                 gn_args):
  if run_tests:
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
    runcmds_path = api.path['tmp_base'].join('runcmds')
    api.file.write_text('write runcmds', runcmds_path, '\n'.join(runcmds))
    api.step.active_result.presentation.logs['runcmds'] = runcmds

    runcmds_package_path = api.path['tmp_base'].join('runcmds_package')
    runcmds_package = RUNCMDS_PACKAGE % runcmds_path
    api.file.write_text('write runcmds package', runcmds_package_path, runcmds_package)
    api.step.active_result.presentation.logs['runcmds_package'] = runcmds_package.splitlines()
    packages.append(str(runcmds_package_path))

  # TODO(abarth): Remove once INTK-99 is fixed.
  packages.append('build/packages/bootfs')

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


def RunTests(api, target, isolated_hash, zircon_build_dir, fuchsia_build_dir):
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
        io_timeout=TEST_IO_TIMEOUT_SECS,
        outputs=['test.fs'],
        cipd_packages=[('qemu', 'fuchsia/qemu/linux-%s' % qemu_cipd_arch, 'latest')],
    )
    # Collect results.
    results = api.swarming.collect('20m', requests_json=api.json.input(trigger_result.json.output))
    assert len(results) == 1
    result = results[0]

  step_result = api.step('task results', None)
  kernel_output_lines = result.output.split('\n')
  step_result.presentation.logs['output'] = kernel_output_lines
  if result.is_infra_failure():
    raise api.step.InfraFailure('Failed to collect: %s' % result.output)
  elif result.is_failure():
    # If the kernel panics, chances are it will result in a task failure since
    # the task will likely time out and QEMU will be forcibly killed.
    if 'KERNEL PANIC' in result.output:
      step_result.presentation.step_text = 'kernel panic'
      step_result.presentation.status = api.step.FAILURE
      Symbolize(api, zircon_build_dir, result.output)
      raise api.step.StepFailure('Found kernel panic. See symbolized output for details.')
    # If we have a timeout with a successful collect, then this must be an
    # io_timeout failure, since task timeout > collect timeout.
    if result.timed_out():
      step_result.presentation.step_text = 'i/o timeout'
      step_result.presentation.status = api.step.FAILURE
      Symbolize(api, zircon_build_dir, result.output)
      failure_lines = [
        'I/O timed out, no output for %s seconds.' % TEST_IO_TIMEOUT_SECS,
        'Last 10 lines of kernel output:',
      ] + kernel_output_lines[-10:]
      raise api.step.StepFailure('\n'.join(failure_lines))
    # At this point its likely an infra issue with QEMU,
    # though a deadlock might also reach this state.
    step_result.presentation.status = api.step.EXCEPTION
    raise api.step.InfraFailure('Swarming task failed:\n%s' % result.output)

  test_results_dir = api.path['start_dir'].join('minfs_isolate_results')
  with api.context(infra_steps=True):
    # Copy test results out of image.
    test_output = api.minfs.cp(
        '::',
        api.raw_io.output_dir(leak_to=test_results_dir),
        result['test.fs'],
        name='extract test results',
        step_test_data=lambda: api.raw_io.test_api.output_dir({
            'hello.out': 'I am output.'
        }),
    ).raw_io.output_dir
    # Read the tests summary.
    test_summary = api.json.read(
        'read test summary',
        test_results_dir.join('summary.json'),
        step_test_data=lambda: api.json.test_api.output({
            'tests': [{'name': '/hello', 'result': 'PASS'}],
        }),
    ).json.output

  # Report test results.
  failed_tests = {}
  step_result = api.step('test results', None)
  for test in test_summary['tests']:
    name = test['name']
    # TODO(mknyszek): make output_name more consistently map to name.
    output_name = name + '.out'
    assert output_name.startswith('/')
    output_name = output_name[1:]
    # TODO(mknyszek): Figure out why '/' is being HTML escaped twice on its way
    # to the output, so this replacement doesn't need to happen.
    log_name = name[1:].replace('/', '.')
    step_result.presentation.logs[log_name] = test_output[output_name].split('\n')
    if test['result'] != 'PASS':
      step_result.presentation.status = api.step.FAILURE
      failed_tests[name] = test_output[output_name]

  # Symbolize the output of any failed tests.
  if len(failed_tests) != 0:
    Symbolize(api, fuchsia_build_dir, '\n'.join(failed_tests.values()))
    raise api.step.StepFailure('Test failure(s): ' + ', '.join(failed_tests.keys()))


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
             target, build_type, packages, variant, run_tests, runtests_args,
             upload_snapshot, goma_dir, gn_args):
  gn_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]
  fuchsia_out_dir = api.path['start_dir'].join('out')
  if build_type in ['release', 'lto', 'thinlto']:
    build_dir = 'release'
  else:
    build_dir = 'debug'
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_dir, gn_target))

  zircon_project = {
    'arm64': 'arm64',
    'x86-64': 'x86'
  }[target]

  zircon_build_dir = fuchsia_out_dir.join('build-zircon', 'build-%s' % zircon_project)

  if goma_dir:
    api.goma.set_goma_dir(goma_dir)

  api.jiri.ensure_jiri()
  api.gsutil.ensure_gsutil()
  api.goma.ensure_goma()
  if run_tests:
    api.swarming.ensure_swarming(version='latest')
    api.isolated.ensure_isolated(version='latest')

  Checkout(api, patch_project, patch_ref, patch_gerrit_url, project, manifest,
           remote, upload_snapshot)

  BuildZircon(api, zircon_project)
  BuildFuchsia(api, build_type, target, gn_target, zircon_project,
               fuchsia_build_dir, packages, variant, run_tests, runtests_args,
               gn_args)

  if run_tests:
    api.minfs.minfs_path = fuchsia_out_dir.join('build-zircon', 'tools', 'minfs')
    digest = IsolateArtifacts(api, target, zircon_build_dir, fuchsia_build_dir)
    RunTests(api, target, digest, zircon_build_dir, fuchsia_build_dir)


def GenTests(api):
  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  ))
  yield api.test('isolated_tests_test_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  )) + api.step_data('read test summary', api.json.output({
      'tests': [{'name': '/hello', 'result': 'FAIL'}],
  })) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))
  yield api.test('isolated_tests_task_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      task_failure=True,
  ))
  yield api.test('isolated_tests_task_timed_out') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      timed_out=True,
  ))
  yield api.test('isolated_tests_kernel_panic') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
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
      run_tests=True,
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
