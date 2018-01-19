# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
  'qemu',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/path',
]

PROPERTIES = {
  'arch': Property(kind=str),
  'kvm': Property(kind=bool, default=False),
}


def RunSteps(api, arch, kvm):
  # First, you need a QEMU.
  api.qemu.ensure_qemu()
  assert api.qemu.qemu_executable(arch)

  # Create an image from an FVM block device.
  backing_file = api.path['start_dir'].join('fvm.blk')
  disk_img = api.path['start_dir'].join('disk.img')
  api.qemu.create_image(disk_img, backing_file)

  # Run an image through QEMU.
  api.qemu.run('test', arch, 'bzImaze',
      kvm=kvm, initrd='disk.img', cmdline='foo=bar', netdev='user,id=net0',
      drives=['file=%s,if=none,format=raw,id=resultsdisk' % api.path.join(api.path['start_dir'], 'qemu.minfs')],
      devices=['e1000,netdev=net0'], shutdown_pattern='goodbye')

  # Run QEMU in the background.
  with api.qemu.background_run(arch, 'bzImage', kvm=kvm):
    api.step('run cmd', ['cmd'])


def GenTests(api):
  for arch in ['aarch64', 'x86_64']:
    yield (
        api.test('basic_%s' % arch) +
        api.properties.generic(arch=arch) +
        api.platform('linux', 64)
    )
    yield (
        api.test('kvm_%s' % arch) +
        api.properties.generic(arch=arch, kvm=True) +
        api.platform('linux', 64)
    )
