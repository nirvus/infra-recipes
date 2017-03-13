#!/usr/bin/env python
# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import fcntl
import os
import platform
import re
import socket
import subprocess
import sys
import time
import threading

from Queue import Queue, Empty


class Watchdog(object):
  '''A timer that can be repeatedly reset.'''

  def __init__(self, timeout, function, args):
    self.timeout = timeout
    self.function = function
    self.args = args
    self.timer = threading.Timer(self.timeout, self.function, self.args)

  def start(self):
    self.timer.start()

  def reset(self):
    self.timer.cancel()
    self.timer = threading.Timer(self.timeout, self.function, self.args)
    self.timer.start()

  def stop(self):
    self.timer.cancel()


def enqueue(stdout, queue, done):
  while not done.isSet():
    try:
      output = stdout.read()
      if not output:
        break
      queue.put(output)
    except IOError:
      pass


def is_kvm_supported(arch):
  return (sys.platform.startswith('linux') and
          platform.machine() == arch and
          os.path.exists('/dev/kvm'))


def main():
  parser = argparse.ArgumentParser(description='Run')
  parser.add_argument('--memory', type=int, default=2048)
  parser.add_argument('--smp', type=int, default=4)
  parser.add_argument('--arch', type=str, default=None)
  parser.add_argument('--kvm', dest='kvm', action='store_true', default=True)
  parser.add_argument('--no-kvm', dest='kvm', action='store_false')
  parser.add_argument('--initrd', type=str, default=None)
  parser.add_argument('--cmdline', type=str, default=None)
  parser.add_argument('--executable', type=str, required=True)
  parser.add_argument('kernel', type=str, default=None)
  args = parser.parse_args()

  cmd = [
    args.executable,
    '-m', str(args.memory),
    '-smp', str(args.smp),
    '-nographic',
    '-machine', {'aarch64': 'virt', 'x86_64': 'q35'}[args.arch],
    '-kernel', args.kernel,
  ]
  if args.kvm and is_kvm_supported(args.arch):
    cmd.extend(['-enable-kvm', '-cpu', 'host'])
  else:
    cmd.extend({
      'aarch64': ['-cpu', 'cortex-a53'],
      'x86_64': ['-cpu', 'Haswell,+smap,-check'],
    }[args.arch])
  if args.initrd:
    cmd.extend(['-initrd', args.initrd])
  if args.cmdline:
    cmd.extend(['-append', args.cmdline])

  qemu = subprocess.Popen(cmd, stdout=subprocess.PIPE)
  flags = fcntl.fcntl(qemu.stdout, fcntl.F_GETFL)
  fcntl.fcntl(qemu.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)

  done = threading.Event()

  queue = Queue()
  thread = threading.Thread(target=enqueue, args=(qemu.stdout, queue, done))
  thread.daemon = True
  thread.start()

  timeout = threading.Event()
  watchdog = Watchdog(60, lambda s: s.set(), [timeout])
  watchdog.start()

  while not timeout.isSet():
    try:
      line = queue.get(False, 1.0)
    except Empty:
      if qemu.poll() is not None:
        watchdog.stop()
        break
    else:
      watchdog.reset()
      sys.stdout.write(line)
      sys.stdout.flush()

  done.set()

  if qemu.poll() is None:
    qemu.kill()

  return qemu.returncode


if __name__ == '__main__':
    sys.exit(main())
