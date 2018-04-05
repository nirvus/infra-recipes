# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building QEMU."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/cipd',
  'infra/gsutil',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/file',
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
  'platform': Property(kind=str, help='Cross-compile to run on platform',
                       default=None),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, platform):
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, patch_ref, patch_gerrit_url)
    revision = api.jiri.project(['third_party/qemu']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  if not platform:
    platform = api.cipd.platform_suffix()

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      packages = {
        'fuchsia/clang/${platform}': 'goma',
      }
      if api.platform.name == 'linux':
        packages.update({
          'fuchsia/sysroot/' + platform: 'latest',
          'infra/cmake/${platform}': 'version:3.9.2',
          'infra/ninja/${platform}': 'version:1.8.2',
        })
      api.cipd.ensure(cipd_dir, packages)

  staging_dir = api.path.mkdtemp('qemu')
  pkg_dir = staging_dir.join('qemu')
  api.file.ensure_directory('create pkg dir', pkg_dir)

  target = {
    'linux-amd64': 'x86_64-linux-gnu',
    'linux-arm64': 'aarch64-linux-gnu',
    'mac-amd64': 'x86_64-apple-darwin',
  }[platform]

  # build SDL2

  if api.platform.name == 'linux':
    sdl_dir = api.path['start_dir'].join('third_party', 'qemu', 'sdl')

    build_dir = staging_dir.join('sdl_build_dir')
    api.file.ensure_directory('create sdl build dir', build_dir)

    install_dir = staging_dir.join('sdl_install_dir')

    env = {
      'CFLAGS': '--target=%s --sysroot=%s' % (target, cipd_dir),
      'CXXFLAGS': '--target=%s --sysroot=%s' % (target, cipd_dir),
      'LDFLAGS': '--target=%s --sysroot=%s' % (target, cipd_dir),
    }

    with api.context(cwd=build_dir, env=env):
      api.step('configure sdl', [
        cipd_dir.join('bin', 'cmake'),
        '-GNinja',
        '-DCMAKE_C_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
        '-DCMAKE_AR=%s' % cipd_dir.join('bin', 'llvm-ar'),
        '-DCMAKE_RANLIB=%s' % cipd_dir.join('bin', 'llvm-ranlib'),
        '-DCMAKE_NM=%s' % cipd_dir.join('bin', 'llvm-nm'),
        '-DCMAKE_CXX_COMPILER=%s' % cipd_dir.join('bin', 'clang++'),
        '-DCMAKE_ASM_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
        '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
        '-DCMAKE_SYSROOT=%s' % cipd_dir,
        '-DCMAKE_INSTALL_PREFIX=%s' % install_dir,
        '-DPKG_CONFIG_EXECUTABLE=',
        '-DVIDEO_WAYLAND=OFF',
        '-DSDL_SHARED=OFF',
        '-DSDL_STATIC_PIC=ON',
        '-DGCC_ATOMICS=ON',
        sdl_dir,
      ])
      api.step('build sdl', [cipd_dir.join('ninja')])
      api.step('install sdl', [cipd_dir.join('ninja'), 'install'])

    env = {
      'PKG_CONFIG_SYSROOT_DIR': cipd_dir,
      'PKG_CONFIG_PATH': cipd_dir.join('usr', 'lib', target, 'pkgconfig'),
      'SDL2_CONFIG': install_dir.join('bin', 'sdl2-config'),
    }
  else:
    env = {}

  # build QEMU

  qemu_dir = api.path['start_dir'].join('third_party', 'qemu')
  build_dir = staging_dir.join('qemu_build_dir')
  api.file.ensure_directory('create qemu build dir', build_dir)

  extra_options = {
    'linux': [
      '--cc=%s' % cipd_dir.join('bin', 'clang'),
      '--cxx=%s' % cipd_dir.join('bin', 'clang++'),
      '--host=%s' % target,
      '--extra-cflags=--target=%s --sysroot=%s' % (target, cipd_dir),
      '--extra-cxxflags=--target=%s --sysroot=%s' % (target, cipd_dir),
      # Supress warning about the unused arguments because QEMU ignores
      # --disable-werror at configure time which triggers an error because
      # -static-libstdc++ is unused when linking C code.
      '--extra-ldflags=--target=%s --sysroot=%s -static-libstdc++ -Qunused-arguments -latomic' % (target, cipd_dir),
      '--disable-gtk',
      '--disable-x11',
      '--enable-sdl',
      '--enable-kvm',
    ],
    'mac': [
      '--enable-cocoa',
    ],
  }[api.platform.name]

  if api.platform.name == 'linux':
    env.update({
      'AR': cipd_dir.join('bin', 'llvm-ar'),
      'RANLIB': cipd_dir.join('bin', 'llvm-ranlib'),
      'NM': cipd_dir.join('bin', 'llvm-nm'),
      'STRIP': cipd_dir.join('bin', 'strip'),
      'OBJCOPY': cipd_dir.join('bin', 'objcopy'),
    })

  with api.context(cwd=build_dir, env=env):
    api.step('configure qemu', [
      qemu_dir.join('configure'),
      '--prefix=',
      '--target-list=aarch64-softmmu,x86_64-softmmu',
      '--without-system-pixman',
      '--without-system-fdt',
      '--disable-vnc-jpeg',
      '--disable-vnc-png',
      '--disable-vnc-sasl',
      '--disable-vte',
      '--disable-docs',
      '--disable-curl',
      '--disable-debug-info',
      '--disable-qom-cast-debug',
      '--disable-guest-agent',
      '--disable-bluez',
      '--disable-brlapi',
      '--disable-gnutls',
      '--disable-gcrypt',
      '--disable-nettle',
      '--disable-virtfs',
      '--disable-vhost-scsi',
      '--disable-vhost-vsock',
      '--disable-libusb',
      '--disable-smartcard',
      '--disable-tasn1',
      '--disable-opengl',
      '--disable-werror',
    ] + extra_options)
    api.step('build qemu', [
      'make',
      '-j%s' % api.platform.cpu_count,
    ])
    with api.context(env={'DESTDIR': pkg_dir}):
      api.step('install qemu', ['make', 'install'])

  qemu_version = api.file.read_text('qemu version', qemu_dir.join('VERSION'),
                                    test_data='2.10.1')
  assert qemu_version, 'Cannot determine QEMU version'

  cipd_pkg_name = 'fuchsia/qemu/' + platform
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return
  cipd_pkg_file = api.path['cleanup'].join('qemu.cipd')

  api.cipd.build(
      input_dir=pkg_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy',
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': qemu_version,
        'git_repository': 'https://fuchsia.googlesource.com/third_party/qemu',
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('qemu', platform, step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def GenTests(api):
  version = 'QEMU emulator version 2.8.0 (v2.8.0-15-g28cd8b6577-dirty)'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.properties(manifest='qemu',
                          remote='https://fuchsia.googlesource.com/manifest') +
           api.step_data('qemu version', api.raw_io.stream_output(version)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.properties(manifest='qemu',
                          remote='https://fuchsia.googlesource.com/manifest') +
           api.step_data('qemu version', api.raw_io.stream_output(version)) +
           api.step_data('cipd search fuchsia/qemu/' + platform + '-amd64 ' +
                         'git_revision:' + api.jiri.example_revision,
                         api.json.output({'result': []})))
  yield (api.test('linux_arm64') +
         api.platform.name('linux') +
         api.properties(manifest='qemu',
                        remote='https://fuchsia.googlesource.com/manifest',
                        platform='linux-arm64') +
         api.step_data('qemu version', api.raw_io.stream_output(version)))
