# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from recipe_engine import recipe_api


class QemuApi(recipe_api.RecipeApi):
  """QemuApi provides support for QEMU."""

  def __init__(self, *args, **kwargs):
    super(QemuApi, self).__init__(*args, **kwargs)
    self._qemu_dir = None

  def ensure_qemu(self, version=None):
    with self.m.step.nest('ensure_qemu'):
      with self.m.step.context({'infra_step': True}):
        qemu_package = ('fuchsia/tools/qemu/%s' %
            self.m.cipd.platform_suffix())
        self._qemu_dir = self.m.path['start_dir'].join('cipd', 'qemu')
        self.m.cipd.ensure(
            self._qemu_dir, {qemu_package: version or 'latest'})
        return self._qemu_dir

  def qemu_executable(self, arch):
    return self.m.path.join(self._qemu_dir, 'bin', 'qemu-system-%s' % arch)

  @contextmanager
  def background_run(self, *args, **kwargs):
    try:
      self.run(*args, action='start', **kwargs)
      yield
    finally:
      self.m.step('stop qemu', [self.resource('qemu.py'), 'stop'])

  def run(self, name, arch, kernel, smp=4, memory=2048, kvm=False, initrd=None,
          cmdline=None, netdev=None, devices=[], action='run',
          step_test_data=None):
    cmd = [
      self.resource('qemu.py'),
      action,
      '--executable', self.qemu_executable(arch),
      '--memory', memory,
      '--smp', smp,
      '--arch', arch,
    ]
    if initrd:
      cmd.extend(['--initrd', initrd])
    if cmdline:
      cmd.extend(['--cmdline', cmdline])
    if netdev:
      cmd.extend(['--netdev', netdev])
    for device in devices:
      cmd.extend(['--device', device])

    cmd.append(kernel)
    return self.m.step(
        name,
        cmd,
        stdin=self.m.raw_io.input(''),
        stdout=self.m.raw_io.output(),
        step_test_data=step_test_data or
            (lambda: self.m.raw_io.test_api.stream_output('qemu'))
    )
