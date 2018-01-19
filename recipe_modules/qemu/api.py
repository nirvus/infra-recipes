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

  def _get_command(self, action, arch, kernel, smp=4, memory=2048, kvm=False,
      initrd=None, cmdline=None, netdev=None, devices=(), drives=(),
      shutdown_pattern=None):
    """Builds the command-line args for the run or start actions."""
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
    for drive in drives:
      cmd.extend(['--drive', drive])
    for device in devices:
      cmd.extend(['--device', device])
    if shutdown_pattern:
      cmd.extend(['--shutdown_pattern', shutdown_pattern])
    cmd.append(kernel)
    return cmd

  def ensure_qemu(self, version=None):
    with self.m.step.nest('ensure_qemu'):
      with self.m.context(infra_steps=True):
        qemu_package = ('fuchsia/tools/qemu/%s' %
            self.m.cipd.platform_suffix())
        self._qemu_dir = self.m.path['start_dir'].join('cipd', 'qemu')
        self.m.cipd.ensure(
            self._qemu_dir, {qemu_package: version or 'latest'})
        return self._qemu_dir

  def qemu_executable(self, arch):
    return self.m.path.join(self._qemu_dir, 'bin', 'qemu-system-%s' % arch)

  @property
  def qemu_img(self):
    return self.m.path.join(self._qemu_dir, 'bin', 'qemu-img')

  @contextmanager
  def background_run(self, *args, **kwargs):
    try:
      self.m.step('start qemu', self._get_command('start', *args, **kwargs))
      yield
    finally:
      self.m.step( 'stop qemu and read log',
          [self.resource('qemu.py'), 'stop', '--log'])

  def create_image(self, image, backing_file, fmt='qcow2'):
    """Creates a QEMU image from a backing file.

    Args:
      image (Path): Path to the image to be created.
      backing_file (Path): The backing file to use for the image.
      fmt (str): The format of the image.
    """
    result = self.m.step(
        'qemu-img create %s' % self.m.path.basename(image),
        [
          self.qemu_img,
          'create',
          '-f', fmt,
          '-b', backing_file,
          image,
        ],
    )
    result.step_text = 'from %s (fmt: %s)' % (
        self.m.path.basename(backing_file),
        fmt,
    )
    return result

  def run(self, step_name, *args, **kwargs):
    step_test_data = kwargs.pop('step_test_data', None)
    timeout = kwargs.pop('timeout', None)
    return self.m.step(
        step_name,
        self._get_command('run', *args, **kwargs),
        timeout=timeout,
        stdin=self.m.raw_io.input(''),
        stdout=self.m.raw_io.output(),
        step_test_data=step_test_data or
            (lambda: self.m.raw_io.test_api.stream_output('qemu')))
