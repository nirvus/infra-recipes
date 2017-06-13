# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import hashlib


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/gsutil',
  'infra/hash',
  'infra/jiri',
  'infra/qemu',
  'infra/tar',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/shutil',
  'recipe_engine/step',
]

TARGETS = ['arm64', 'x86-64']

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
  'build_type': Property(kind=Enum('debug', 'release'), help='The build type',
                         default='debug'),
  'modules': Property(kind=List(basestring), help='Packages to build',
                      default=['default']),
  'boot_module': Property(kind=str,
                          help='Package to build that specifies boot behavior.',
                          default=None),
  'tests': Property(kind=str, help='Path to config file listing tests to run',
                    default=None),
  'use_goma': Property(kind=bool, help='Whether to use goma to compile',
                       default=True)
}

TEST_RUNNER_PORT = 8342


def Checkout(api, patch_ref, patch_gerrit_url, manifest, remote):
  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, overwrite=True)
    api.jiri.clean(all=True)
    api.jiri.update(gc=True)
    if not api.properties.get('tryjob', False):
      snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
      step_result = api.jiri.snapshot(api.raw_io.output(leak_to=snapshot_file))
      digest = hashlib.sha1(step_result.raw_io.output).hexdigest()
      api.gsutil.upload('fuchsia', snapshot_file, 'jiri/snapshots/' + digest,
          link_name='jiri.snapshot',
          name='upload jiri.snapshot',
          unauthenticated_url=True)

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url, rebase=True)


def BuildMagenta(api, target):
  magenta_target = {'arm64': 'aarch64', 'x86-64': 'x86_64'}[target]
  build_magenta_cmd = [
    api.path['start_dir'].join('scripts', 'build-magenta.sh'),
    '-c',
    '-t', magenta_target,
  ]
  api.step('build magenta', build_magenta_cmd)


@contextmanager
def GomaContext(api, use_goma):
  if not use_goma:
    yield
  else:
    with api.goma.build_with_goma():
      yield


def BuildFuchsia(api, release_build, target, gn_target, fuchsia_build_dir,
                 modules, boot_module, tests, use_goma):
  if tests and not boot_module:
    boot_module = 'boot_test_runner'

  if boot_module:
    modules.append(boot_module)

  with api.step.nest('build fuchsia'), GomaContext(api, use_goma):
    gen_cmd = [
      api.path['start_dir'].join('packages', 'gn', 'gen.py'),
      '--target_cpu=%s' % gn_target,
      '--modules=%s' % ','.join(modules),
      '--with-dart-analysis',
    ]

    if use_goma:
      gen_cmd.append('--goma=%s' % api.goma.goma_dir)

    if release_build:
      gen_cmd.append('--release')

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


def RunTests(api, target, fuchsia_build_dir, tests):
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

  netdev = 'user,id=net0,hostfwd=tcp::%d-:%d' % (
      TEST_RUNNER_PORT, TEST_RUNNER_PORT)

  qemu = api.qemu.background_run(
      qemu_arch,
      magenta_image_path,
      kvm=True,
      memory=4096,
      initrd=bootfs_path,
      netdev=netdev,
      devices=['e1000,netdev=net0'])

  try:
    with qemu:
      run_tests_cmd = [
        api.path['start_dir'].join('apps', 'test_runner', 'src', 'run_test'),
        '--test_file', api.path['start_dir'].join(tests),
        '--server', '127.0.0.1',
        '--port', str(TEST_RUNNER_PORT),
      ]
      api.step('run tests', run_tests_cmd)
  finally:
    symbolize_cmd = [
      api.path['start_dir'].join('magenta', 'scripts', 'symbolize'),
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
             build_type, modules, boot_module, tests, use_goma):
  # Tests are currently broken on arm64.
  if target == 'arm64':
    tests = None

  release_build = (build_type == 'release')
  gn_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]
  fuchsia_out_dir = api.path['start_dir'].join('out')
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_type, gn_target))

  magenta_target = {
    'arm64': 'magenta-qemu-arm64',
    'x86-64': 'magenta-pc-x86-64'
  }[target]
  magenta_build_dir = fuchsia_out_dir.join('build-magenta', 'build-%s' % magenta_target)

  api.jiri.ensure_jiri()
  api.gsutil.ensure_gsutil()
  api.gsutil.set_boto_config(api.gsutil.default_boto_config)
  if use_goma:
    api.goma.ensure_goma()
  if tests:
    api.qemu.ensure_qemu()

  Checkout(api, patch_ref, patch_gerrit_url, manifest, remote)
  BuildMagenta(api, target)
  BuildFuchsia(api, release_build, target, gn_target, fuchsia_build_dir,
               modules, boot_module, tests, use_goma)

  if tests:
    RunTests(api, target, fuchsia_build_dir, tests)

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
      tests='tests.json',
  )
  yield api.test('boot_module') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='tests.json',
      boot_module='boot_special',
  )
  yield api.test('failed_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='tests.json',
  ) + api.step_data('run tests', retcode=1)
  yield api.test('backtrace') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tests='tests.json',
  ) + api.step_data('run tests', retcode=1,
  ) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))
  yield api.test('no_goma') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      use_goma=False,
  )
  yield api.test('arm64_skip_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      tests='tests.json',
      target='arm64',
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='release'
  )
  yield api.test('cq') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      tryjob=True,
  )
