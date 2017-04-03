#!/usr/bin/env python
# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import fcntl
import os
import platform
import re
import signal
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


def stop_qemu():
  pid = int(open('qemu.pid').read())
  os.kill(pid, signal.SIGTERM)

  while True:
    time.sleep(0.5)
    try:
      os.kill(pid, 0)
    except OSError:  # process completed
      break


def main():
  main_parser = argparse.ArgumentParser(description='QEMU')
  subparsers = main_parser.add_subparsers(dest='command')
  run_parser = subparsers.add_parser('run',
      description='run QEMU in the foreground')
  start_parser = subparsers.add_parser('start',
      description='start QEMU in the background')
  stop_parser = subparsers.add_parser('stop',
      description='stop the background QEMU process')

  for parser in run_parser, start_parser:
    parser.add_argument('--memory', type=int, default=2048)
    parser.add_argument('--smp', type=int, default=4)
    parser.add_argument('--arch', type=str, required=True)
    parser.add_argument('--kvm', dest='kvm', action='store_true', default=True)
    parser.add_argument('--no-kvm', dest='kvm', action='store_false')
    parser.add_argument('--initrd', type=str, default=None)
    parser.add_argument('--cmdline', type=str, default=None)
    parser.add_argument('--executable', type=str, required=True)
    parser.add_argument('--netdev', type=str, default=None)
    parser.add_argument('--device', type=str, action='append', default=[])
    parser.add_argument('kernel', type=str, default=None)

  args = main_parser.parse_args()

  if args.command == 'stop':
    stop_qemu()
    return 0

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
  if args.netdev:
    cmd.extend(['-netdev', args.netdev])
  for device in args.device:
    cmd.extend(['-device', device])

  if args.command == 'start':
    daemon = True
    if os.fork() != 0:
      os._exit(0)
    stdout = open('qemu.stdout', 'w')
  else:
    daemon = False
    stdout = sys.stdout

  qemu = subprocess.Popen(cmd, stdout=subprocess.PIPE)
  flags = fcntl.fcntl(qemu.stdout, fcntl.F_GETFL)
  fcntl.fcntl(qemu.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)

  if daemon:
    with open('qemu.pid', 'w') as pidfile:
      pidfile.write(str(qemu.pid) + '\n')

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
      stdout.write(line)
      stdout.flush()

  done.set()

  if qemu.poll() is None:
    qemu.kill()

  if daemon:
    os.remove('qemu.pid')

  return qemu.returncode


if __name__ == '__main__':
    sys.exit(main())
