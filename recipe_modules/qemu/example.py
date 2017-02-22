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
]

PROPERTIES = {
  'arch': Property(kind=str),
  'kvm': Property(kind=bool, default=False),
}


def RunSteps(api, arch, kvm):
  # First, you need a QEMU.
  api.qemu.ensure_qemu()
  assert api.qemu.qemu_executable(arch)

  # Run an image through QEMU.
  api.qemu.run(arch, 'bzImaze', kvm=kvm, initrd='disk.img', cmdline='foo=bar')


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
