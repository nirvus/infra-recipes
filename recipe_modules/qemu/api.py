# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import ast


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

  def is_kvm_supported(self, arch):
    return self.m.platform.is_linux and ast.literal_eval(self.m.python.inline(
        'check if kvm is supported',
        """
        import os
        import platform
        import sys
        print platform.processor() == sys.argv[1] and os.path.exists('/dev/kvm')
        """,
        args=[arch],
        stdout=self.m.raw_io.output(),
        step_test_data=lambda:
            self.m.raw_io.test_api.stream_output('True\n'),
        add_python_log=False
    ).stdout)

  def run(self, arch, kernel, smp=4, memory=2048, kvm=False, initrd=None,
          cmdline=None, timeout=300, step_test_data=None):
    cmd = [
      self.qemu_executable(arch),
      '-nographic',
      '-m', memory,
      '-smp', smp,
      '-machine', {'aarch64': 'virt', 'x86_64': 'q35'}[arch],
      '-kernel', kernel,
    ]
    if self.is_kvm_supported(arch) and kvm:
      cmd.extend(['-enable-kvm', '-cpu', 'host'])
    else:
      cmd.extend({
        'aarch64': ['-cpu', 'cortex-a53'],
        'x86_64': ['-cpu', 'Haswell,+smap,-check'],
      }[arch])
    if initrd:
      cmd.extend(['-initrd', initrd])
    cmd.extend(['-append', 'TERM=vt100'])
    if cmdline:
      cmd.append(cmdline)
    return self.m.step(
        'run %s' % self.m.path.basename(kernel),
        cmd,
        timeout=timeout,
        stdin=self.m.raw_io.input(''),
        stdout=self.m.raw_io.output(),
        stderr=self.m.raw_io.output(),
        step_test_data=step_test_data or
            (lambda: self.m.raw_io.test_api.stream_output('qemu'))
    )
