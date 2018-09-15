#!/usr/bin/env python
# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recursively copies files that match given pattern.

Usage:
  python copy_files.py path/to/src path/to/dst lib*/*.h
"""

import argparse
import fnmatch
import os
import shutil
import sys


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('src', help='source path')
  parser.add_argument('dst', help='destination path')
  parser.add_argument('pattern', nargs='+', action='store', help='pattern')
  args = parser.parse_args()

  for path, _, files in os.walk(os.path.abspath(args.src)):
    for file in files:
      srcname = os.path.join(path, file)
      relpath = os.path.relpath(srcname, args.src)
      dstname = os.path.join(args.dst, relpath)
      for pattern in args.pattern:
        if fnmatch.fnmatch(relpath, pattern):
          dirname = os.path.dirname(dstname)
          if not os.path.exists(dirname):
            os.makedirs(dirname)
          shutil.copy(srcname, dstname)

  return 0


if __name__ == '__main__':
  sys.exit(main())
