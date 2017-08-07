# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Clang toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re
import hashlib


DEPS = [
  'infra/cipd',
  'infra/gsutil',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

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
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote):
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()

  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, overwrite=True)
    api.jiri.clean(all=True)
    api.jiri.update(gc=True)
    snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
    step_result = api.jiri.snapshot(api.raw_io.output(leak_to=snapshot_file))
    digest = hashlib.sha1(step_result.raw_io.output).hexdigest()
    api.gsutil.upload('fuchsia', snapshot_file, 'jiri/snapshots/' + digest,
        link_name='jiri.snapshot',
        name='upload jiri.snapshot',
        unauthenticated_url=True)

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
        'fuchsia/tools/cmake/${platform}': 'latest',
        'fuchsia/tools/ninja/${platform}': 'latest',
      })

  staging_dir = api.path.mkdtemp('clang')
  pkg_name = 'clang+llvm-x86_64-%s' % api.platform.name.replace('mac', 'darwin')
  pkg_dir = staging_dir.join(pkg_name)
  api.file.ensure_directory('create pkg dir', pkg_dir)

  # build binutils
  # TODO: remove this once we have objcopy/strip replacement
  binutils_dir = api.path['start_dir'].join('third_party', 'binutils-gdb')

  build_dir = staging_dir.join('binutils_build_dir')
  api.file.ensure_directory('create binutils build dir', build_dir)

  install_dir = staging_dir.join('binutils_install_dir')

  with api.context(cwd=build_dir):
    api.step('configure binutils', [
      binutils_dir.join('configure'),
      '--prefix=',
      '--program-prefix=',
      '--enable-targets=aarch64-elf,x86_64-elf,x86_64-darwin',
      '--enable-deterministic-archives',
      '--disable-werror',
      '--disable-nls',
    ])
    api.step('build binutils', [
      'make',
      '-j%s' % api.platform.cpu_count,
      'all-binutils',
    ])
    with api.context(env={'DESTDIR': install_dir}):
      api.step('install binutils', [
        'make',
        'install-strip-binutils',
      ])

  api.file.ensure_directory('create bin dir', pkg_dir.join('bin'))
  api.file.copy('copy objcopy',
                install_dir.join('bin', 'objcopy'),
                pkg_dir.join('bin', 'objcopy'))
  api.file.copy('copy strip',
                install_dir.join('bin', 'strip'),
                pkg_dir.join('bin', 'strip'))

  # build magenta
  magenta_dir = api.path['start_dir'].join('magenta')

  for target in ['magenta-qemu-arm64', 'magenta-pc-x86-64']:
    with api.context(cwd=magenta_dir):
      api.step('build %s' % target, [
        'make',
        '-j%s' % api.platform.cpu_count,
        target,
      ])

  # build clang+llvm
  llvm_dir = api.path['start_dir'].join('third_party', 'llvm')
  clang_dir = llvm_dir.join('tools', 'clang')

  build_dir = staging_dir.join('llvm_build_dir')
  api.file.ensure_directory('create llvm build dir', build_dir)

  toolchain_dir = api.path['start_dir'].join('buildtools', 'toolchain')

  with api.context(cwd=build_dir):
    api.step('configure clang', [
      cipd_dir.join('bin', 'cmake'),
      '-GNinja',
      '-DCMAKE_C_COMPILER=%s' % toolchain_dir.join(pkg_name, 'bin', 'clang'),
      '-DCMAKE_CXX_COMPILER=%s' % toolchain_dir.join(pkg_name, 'bin', 'clang++'),
      '-DCMAKE_ASM_COMPILER=%s' % toolchain_dir.join(pkg_name, 'bin', 'clang'),
      '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
      '-DCMAKE_INSTALL_PREFIX=',
      '-DFUCHSIA_x86_64_SYSROOT=%s' % magenta_dir.join('build-magenta-pc-x86-64', 'sysroot'),
      '-DFUCHSIA_aarch64_SYSROOT=%s' % magenta_dir.join('build-magenta-qemu-arm64', 'sysroot'),
      '-C', clang_dir.join('cmake', 'caches', 'Fuchsia.cmake'),
      llvm_dir,
    ])
    api.step('build clang', [cipd_dir.join('ninja'), 'stage2-distribution'])
    with api.context(env={'DESTDIR': pkg_dir}):
      api.step('install clang',
               [cipd_dir.join('ninja'), 'stage2-install-distribution'])

  # use first rather than second stage clang just in case we're cross-compiling
  step_result = api.step('clang version',
      [build_dir.join('bin', 'clang'), '--version'],
      stdout=api.raw_io.output())
  m = re.search(r'\([^ ]+ (\w+)\) \([^ ]+ (\w+)\)', step_result.stdout)
  assert m, 'Cannot determine Clang version'
  clang_revision = m.group(1)
  llvm_revision = m.group(2)

  cipd_pkg_name = 'fuchsia/clang/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'clang_revision:' + clang_revision)
  if step.json.output['result']:
    return
  cipd_pkg_file = api.path['tmp_base'].join('clang.cipd')

  api.cipd.build(
      input_dir=pkg_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'clang_revision': clang_revision,
        'llvm_revision': llvm_revision,
        'jiri_snapshot': digest,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      '/'.join(['clang', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']]),
      unauthenticated_url=True
  )


def GenTests(api):
  version = 'clang version 5.0.0 (trunk 302207) (llvm/trunk 302209)'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.properties(manifest='toolchain',
                          remote='https://fuchsia.googlesource.com/manifest') +
           api.step_data('clang version', api.raw_io.stream_output(version)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.properties(manifest='toolchain',
                          remote='https://fuchsia.googlesource.com/manifest') +
           api.step_data('clang version', api.raw_io.stream_output(version)) +
           api.step_data('cipd search fuchsia/clang/' + platform + '-amd64 ' +
                         'clang_revision:302207',
                         api.json.output({'result': []})))