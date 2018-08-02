#!/usr/bin/env python
# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Creates a new symlink.

Usage:
  python create_symlink.py target link_name
"""

import argparse
import os
import shutil
import sys


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('source', help='symlink target')
  parser.add_argument('link_name', help='symlink name')
  args = parser.parse_args()

  if sys.platform == 'linux2' or sys.platform == 'darwin':
    os.symlink(args.source, args.link_name)
  else:
    shutil.copytree(args.source, args.link_name)

  return 0


if __name__ == '__main__':
  sys.exit(main())
