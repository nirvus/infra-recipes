#!/usr/bin/env python
# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import hashlib
import sys


def compute(algorithm, file):
  hash = hashlib.new(algorithm)
  with open(file, "rb") as f:
    for chunk in iter(lambda: f.read(4096), b""):
      hash.update(chunk)
  return hash.hexdigest()


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('-a', '--algorithm', default='sha1',
      choices=['md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512'])
  parser.add_argument('file')

  args = parser.parse_args()

  print compute(args.algorithm, args.file)


if __name__ == '__main__':
  sys.exit(main())
