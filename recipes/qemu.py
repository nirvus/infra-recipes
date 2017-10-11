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
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote):
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()

  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, patch_ref, patch_gerrit_url)
    revision = api.jiri.project(['third_party/qemu']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      if api.platform.name == 'linux':
        api.cipd.ensure(cipd_dir, {
          'fuchsia/clang/${platform}': 'latest',
          'fuchsia/sysroot/${platform}': 'latest',
        })

  staging_dir = api.path.mkdtemp('qemu')
  pkg_dir = staging_dir.join('qemu')
  api.file.ensure_directory('create pkg dir', pkg_dir)

  qemu_dir = api.path['start_dir'].join('third_party', 'qemu')
  build_dir = api.path.mkdtemp('build')

  extra_options = {
    'linux': [
      '--cc=%s' % cipd_dir.join('bin', 'clang'),
      '--cxx=%s' % cipd_dir.join('bin', 'clang++'),
      '--extra-cflags="--sysroot=%s"' % cipd_dir,
      '--extra-cxxflags="--sysroot=%s"' % cipd_dir,
      '--extra-ldflags="-static-libstdc++ --sysroot=%s"' % cipd_dir,
      '--disable-gtk',
      '--enable-sdl=internal',
      '--enable-kvm',
    ],
    'mac': [
      '--enable-cocoa',
    ],
  }[api.platform.name]

  with api.context(cwd=build_dir):
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
      '--disable-tools',
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

  step_result = api.step('qemu version',
      [build_dir.join('x86_64-softmmu', 'qemu-system-x86_64'), '--version'],
      stdout=api.raw_io.output())
  m = re.search(r'version ([0-9.-]+)', step_result.stdout)
  assert m, 'Cannot determine QEMU version'
  qemu_version = m.group(1)

  cipd_pkg_name = 'fuchsia/qemu/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return
  cipd_pkg_file = api.path['tmp_base'].join('qemu.cipd')

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
      'version': qemu_version,
      'git_repository': 'https://fuchsia.googlesource.com/third_party/qemu',
      'git_revision': revision,
    },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('qemu', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
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
