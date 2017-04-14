# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/jiri',
  'infra/qemu',
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
  'build_variant': Property(kind=Enum('incremental', 'full'),
                            help='The build variant', default='full'),
  'build_type': Property(kind=Enum('debug', 'release'), help='The build type',
                         default='debug'),
  'modules': Property(kind=List(basestring), help='Packages to build',
                      default=['default']),
  'tests': Property(kind=str, help='Path to config file listing tests to run',
                    default=None),
  'use_goma': Property(kind=bool, help='Whether to use goma to compile',
                       default=True)
}

TEST_RUNNER_PORT = 8342


def Checkout(api, start_dir, patch_ref, patch_gerrit_url, build_variant,
             manifest, remote):
  with api.step.context({'cwd': start_dir}):
    with api.step.context({'infra_step': True}):
      api.jiri.init()
      api.jiri.import_manifest(manifest, remote, overwrite=True)
      api.jiri.clean(all=True)
      api.jiri.update(gc=True)
      step_result = api.jiri.snapshot(api.raw_io.output())
      snapshot = step_result.raw_io.output
      step_result.presentation.logs['jiri.snapshot'] = snapshot.splitlines()

    if patch_ref is not None:
      api.jiri.patch(patch_ref, host=patch_gerrit_url)

def BuildSysroot(api, start_dir, release_build, target):
  sysroot_target = {'arm64': 'aarch64', 'x86-64': 'x86_64'}[target]
  build_sysroot_cmd = [
    start_dir.join('scripts/build-sysroot.sh'),
    '-c',
    '-t', sysroot_target,
  ]

  if release_build:
    build_sysroot_cmd.append('-r')

  api.step('build sysroot', build_sysroot_cmd)

@contextmanager
def GomaContext(api, use_goma):
  if not use_goma:
    yield
  else:
    with api.goma.build_with_goma():
      yield

def BuildFuchsia(api, start_dir, release_build, target, gn_target,
                 fuchsia_build_dir, modules, tests, use_goma):
  if tests:
    # boot_test_modular starts up the test runner.
    # TODO(bgoldman): create a more general package for running tests.
    modules.append('boot_test_modular')

  with api.step.nest('build fuchsia'), GomaContext(api, use_goma):
    gen_cmd = [
      start_dir.join('packages/gn/gen.py'),
      '--target_cpu=%s' % gn_target,
      '--modules=%s' % ','.join(modules),
    ]

    if use_goma:
      gen_cmd.append('--goma=%s' % api.goma.goma_dir)

    if release_build:
      gen_cmd.append('--release')

    api.step('gen', gen_cmd)

    ninja_cmd = [
      start_dir.join('buildtools/ninja'),
      '-C', fuchsia_build_dir,
    ]

    if use_goma:
        ninja_cmd.extend(['-j', api.goma.recommended_goma_jobs])
    else:
        ninja_cmd.extend(['-j', api.platform.cpu_count])

    api.step('ninja', ninja_cmd)

def RunTests(api, start_dir, target, gn_target, fuchsia_out_dir,
             fuchsia_build_dir, build_type, tests):
  magenta_build_dir = {
    'arm64': 'build-magenta-qemu-arm64',
    'x86-64': 'build-magenta-pc-x86-64',
  }[target]

  magenta_image_name = {
    'arm64': 'magenta.elf',
    'x86-64': 'magenta.bin',
  }[target]

  magenta_image_path = start_dir.join(
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

  with qemu:
    run_tests_cmd = [
      start_dir.join('apps/test_runner/src/run_test'),
      '--test_file', start_dir.join(tests),
      '--server', '127.0.0.1',
      '--port', str(TEST_RUNNER_PORT),
    ]

    context = {
      'env': {
        'FUCHSIA_OUT_DIR': fuchsia_out_dir,
        'FUCHSIA_BUILD_DIR': fuchsia_build_dir,
      },
    }

    # TODO(bgoldman): Update run_test so that it gives exit status and also
    # retries the TCP connection at startup.
    # - Exit status is necessary to tell if the tests passed, not just if they
    #   completed.
    # - Retry is to deal with a possible race condition where QEMU is not
    #   forwarding the port by the time run_tests tries to connect. I haven't
    #   actually seen this happen yet.
    with api.step.context(context):
      api.step('run tests', run_tests_cmd)

def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             build_variant, build_type, modules, tests, use_goma):
  if build_variant == 'incremental':
    start_dir = api.path['cache'].join('fuchsia')
  else:
    start_dir = api.path['start_dir']

  release_build = (build_type == 'release')
  gn_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]
  fuchsia_out_dir = start_dir.join('out')
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_type, gn_target))

  api.jiri.ensure_jiri()
  if use_goma:
    api.goma.ensure_goma()
  if tests:
    api.qemu.ensure_qemu()

  Checkout(api, start_dir, patch_ref, patch_gerrit_url, build_variant, manifest,
           remote)
  BuildSysroot(api, start_dir, release_build, target)
  BuildFuchsia(api, start_dir, release_build, target, gn_target,
               fuchsia_build_dir, modules, tests, use_goma)

  if tests:
    RunTests(api, start_dir, target, gn_target, fuchsia_out_dir,
             fuchsia_build_dir, build_type, tests)

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
  yield api.test('no_goma') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      use_goma=False,
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_type='release'
  )
  yield api.test('incremental') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      build_variant='incremental',
  )
  yield api.test('cq') + api.properties.tryserver(
      gerrit_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
  )
