# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property, StepFailure

import hashlib
import re


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/gsutil',
  'infra/hash',
  'infra/jiri',
  'infra/qemu',
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

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'build_type': Property(kind=Enum('debug', 'release', 'thinlto', 'lto'),
                         help='The build type', default='debug'),
  'modules': Property(kind=List(basestring), help='Packages to build',
                      default=['boot_headless']),
  'tests': Property(kind=str, help='Command to run tests',
                    default='runtests /system/test'),
  'use_goma': Property(kind=bool, help='Whether to use goma to compile',
                       default=True),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
}


def Checkout(api, patch_project, patch_ref, patch_gerrit_url, manifest, remote):
  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, overwrite=True)
    api.jiri.clean(all=True)
    api.jiri.update(gc=True)

    snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
    step_result = api.jiri.snapshot(
        api.raw_io.output(name='snapshot', leak_to=snapshot_file),
        source_manifest=api.json.output(name='source manifest'))
    api.source_manifest.set_json_manifest('checkout', step_result.json.output)
    if not api.properties.get('tryjob', False):
      digest = api.hash.sha1('hash snapshot', snapshot_file,
                             test_data='8ac5404b688b34f2d34d1c8a648413aca30b7a97')
      api.gsutil.upload('fuchsia', snapshot_file, 'jiri/snapshots/' + digest,
          link_name='jiri.snapshot',
          name='upload jiri.snapshot',
          unauthenticated_url=True)

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url, rebase=True)
    if patch_project == 'manifest':
      api.jiri.update(gc=True, local_manifest=True)


def BuildMagenta(api, target, tests):
  if tests:
    autorun = ['msleep 500', tests]
    autorun_path = api.path['tmp_base'].join('autorun')
    api.file.write_text('write autorun', autorun_path, '\n'.join(autorun))
    api.step.active_result.presentation.logs['autorun.sh'] = autorun
    build_env = {'USER_AUTORUN': autorun_path}
  else:
    build_env = {}

  magenta_target = {'arm64': 'aarch64', 'x86-64': 'x86_64'}[target]
  build_magenta_cmd = [
    api.path['start_dir'].join('scripts', 'build-magenta.sh'),
    '-c',
    '-t', magenta_target,
  ]

  with api.context(env=build_env):
    api.step('build magenta', build_magenta_cmd)


@contextmanager
def GomaContext(api, use_goma):
  if not use_goma:
    yield
  else:
    with api.goma.build_with_goma():
      yield


def BuildFuchsia(api, build_type, target, gn_target, fuchsia_build_dir,
                 modules, use_goma, gn_args):
  with api.step.nest('build fuchsia'), GomaContext(api, use_goma):
    gen_cmd = [
      api.path['start_dir'].join('packages', 'gn', 'gen.py'),
      '--target_cpu=%s' % gn_target,
      '--modules=%s' % ','.join(modules),
      '--with-dart-analysis',
    ]

    if use_goma:
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

    if use_goma:
        ninja_cmd.extend(['-j', api.goma.recommended_goma_jobs])
    else:
        ninja_cmd.extend(['-j', api.platform.cpu_count])

    api.step('ninja', ninja_cmd)


def RunTests(api, target, fuchsia_build_dir):
  magenta_build_dir = {
    'arm64': 'build-magenta-qemu-arm64',
    'x86-64': 'build-magenta-pc-x86-64',
  }[target]

  magenta_image_name = {
    'arm64': 'magenta.elf',
    'x86-64': 'magenta.bin',
  }[target]

  magenta_image_path = api.path['start_dir'].join(
    'out', 'build-magenta', magenta_build_dir, magenta_image_name)

  bootfs_path = fuchsia_build_dir.join('user.bootfs')

  qemu_arch = {
    'arm64': 'aarch64',
    'x86-64': 'x86_64',
  }[target]

  step_result = None

  try:
    step_result = api.qemu.run(
        'run tests',
        qemu_arch,
        magenta_image_path,
        kvm=True,
        memory=4096,
        initrd=bootfs_path,
        shutdown_pattern=TEST_SUMMARY)
  except StepFailure as error:
    step_result = error.result
    if error.retcode == 2:
      message = "Tests timed out"
    else:
      message = "QEMU failure"
    raise api.step.StepFailure(message)
  finally:
    if step_result is not None:
      qemu_log = step_result.stdout
      step_result.presentation.logs['qemu log'] = qemu_log.splitlines()

      symbolize_cmd = [
        api.path['start_dir'].join('magenta', 'scripts', 'symbolize'),
        '--no-echo',
        '--build-dir', fuchsia_build_dir,
      ]

      step_result = api.step('symbolize', symbolize_cmd,
          stdin=api.raw_io.input(data=qemu_log),
          stdout=api.raw_io.output(),
          step_test_data=lambda: api.raw_io.test_api.stream_output(''))

      lines = step_result.stdout.splitlines()
      if lines:
        # If symbolize found any backtraces in qemu.stdout, mark the symbolize
        # step as failed to indicate that it should be looked at.
        step_result.presentation.logs['symbolized backtraces'] = lines
        step_result.presentation.status = api.step.FAILURE

  m = re.search(TEST_SUMMARY, qemu_log)
  if not m:
    step_result.presentation.status = api.step.WARNING
    raise api.step.StepWarning('Test output missing')
  elif int(m.group('failed')) > 0:
    step_result.presentation.status = api.step.FAILURE
    raise api.step.StepFailure(m.group(0))


def UploadArchive(api, target, magenta_build_dir, fuchsia_build_dir):
  api.tar.ensure_tar()

  package = api.tar.create(api.path['tmp_base'].join('fuchsia.tar.gz'), 'gzip')
  package.add(fuchsia_build_dir.join('user.bootfs'), fuchsia_build_dir)
  package.add(magenta_build_dir.join('bootdata.bin'), magenta_build_dir)
  package.add(magenta_build_dir.join('magenta.elf'), magenta_build_dir)
  if target == 'x86-64':
    package.add(magenta_build_dir.join('magenta.bin'), magenta_build_dir)
    package.add(magenta_build_dir.join('bootloader', 'bootx64.efi'), magenta_build_dir)
  package.tar('tar fuchsia')
  digest = api.hash.sha1('hash archive', package.archive,
                         test_data='cd963da3f17c3acc611a9b9c1b272fcd6ae39909')
  api.gsutil.upload('fuchsia-archive', package.archive, digest,
      link_name='fuchsia.tar.gz',
      name='upload fuchsia.tar.gz')


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             build_type, modules, tests, use_goma, gn_args):
  gn_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]
  fuchsia_out_dir = api.path['start_dir'].join('out')
  if build_type in ['release', 'lto', 'thinlto']:
    build_dir = 'release'
  else:
    build_dir = 'debug'
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_dir, gn_target))

  magenta_target = {
    'arm64': 'magenta-qemu-arm64',
    'x86-64': 'magenta-pc-x86-64'
  }[target]
  magenta_build_dir = fuchsia_out_dir.join('build-magenta', 'build-%s' % magenta_target)

  api.jiri.ensure_jiri()
  api.gsutil.ensure_gsutil()
  if use_goma:
    api.goma.ensure_goma()
  if tests:
    api.qemu.ensure_qemu()

  Checkout(api, patch_project, patch_ref, patch_gerrit_url, manifest, remote)
  BuildMagenta(api, target, tests)
  BuildFuchsia(api, build_type, target, gn_target, fuchsia_build_dir,
               modules, use_goma, gn_args)

  if tests:
    RunTests(api, target, fuchsia_build_dir)

  if not api.properties.get('tryjob', False):
    UploadArchive(api, target, magenta_build_dir, fuchsia_build_dir)


def GenTests(api):
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  )
  yield api.test('tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 0 failed'))
  yield api.test('failed_qemu') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  ) + api.step_data('run tests', retcode=1)
  yield api.test('tests_timeout') + api.properties(
        manifest='fuchsia',
        remote='https://fuchsia.googlesource.com/manifest',
        target='x86-64',
  ) + api.step_data('run tests', retcode=2)
  yield api.test('failed_tests') + api.properties(
        manifest='fuchsia',
        remote='https://fuchsia.googlesource.com/manifest',
        target='x86-64',
  ) + api.step_data('run tests', api.raw_io.stream_output('SUMMARY: Ran 2 tests: 1 failed'))
  yield api.test('backtrace') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  ) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))
  yield api.test('no_goma') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      use_goma=False,
      tests=None,
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='release',
      tests=None,
  )
  yield api.test('lto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='lto',
      tests=None,
  )
  yield api.test('thinlto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='thinlto',
      tests=None,
  )
  yield api.test('cq') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tryjob=True,
      tests=None,
  )
  yield api.test('gn_args') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tryjob=True,
      gn_args=['super_arg=false', 'less_super_arg=true'],
      tests=None,
  )
  yield api.test('manifest') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_project='manifest',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tryjob=True,
      tests=None,
  )
