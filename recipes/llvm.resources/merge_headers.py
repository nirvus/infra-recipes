#!/usr/bin/env python
# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Merges headers from two different paths, surrounding differing blocks with
macro guards that can be specified via command line argument.

Usage:
  python merge_headers.py --def1=__aarch64__ --def2=__x86_64__ out/arm64 out/x64
"""

import argparse
import difflib
import filecmp
import os
import shutil
import sys


def copyfile(src_a, src_b, dst, def_a=None, def_b=None):
  if filecmp.cmp(src_a, src_b):
    shutil.copyfile(src_a, dst)
    return

  with open(src_a, 'r') as f:
    a = f.readlines()
  with open(src_b, 'r') as f:
    b = f.readlines()

  s = difflib.SequenceMatcher(None, a, b)
  out = []
  blocks = s.get_matching_blocks()
  for i in range(0, len(blocks) - 1):
    out.extend(a[blocks[i].a:blocks[i].a+blocks[i].size])
    diff_a = a[blocks[i].a+blocks[i].size:blocks[i+1].a]
    if diff_a and def_a:
      out.extend(['#ifdef %s\n' % def_a] + diff_a + ['#endif\n'])
    diff_b = b[blocks[i].b+blocks[i].size:blocks[i+1].b]
    if diff_b and def_b:
      out.extend(['#ifdef %s\n' % def_b] + diff_b + ['#endif\n'])

  with open(dst, 'w') as f:
    f.writelines(out)


def copytree(src_a, src_b, dst, def_a=None, def_b=None):
  names = os.listdir(src_a)
  if not os.path.isdir(dst):
    os.makedirs(dst)
  for name in names:
    srcname_a = os.path.join(src_a, name)
    srcname_b = os.path.join(src_b, name)
    dstname = os.path.join(dst, name)
    try:
      if os.path.islink(srcname_a):
        linkto = os.readlink(srcname_a)
        os.symlink(linkto, dstname)
      elif os.path.isdir(srcname_a):
        copytree(srcname_a, srcname_b, dstname, def_a, def_b)
      else:
        copyfile(srcname_a, srcname_b, dstname, def_a, def_b)
    except Exception:
      shutil.rmtree(dst, ignore_errors=True)
      raise


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('-o', '--out', default=os.getcwd(),
                      help='destination path')
  parser.add_argument('--def1', help='define value for first path')
  parser.add_argument('--def2', help='define value for second path')
  parser.add_argument('path1', help='first path')
  parser.add_argument('path2', help='second path')
  args = parser.parse_args()

  copytree(args.path1, args.path2, args.out, args.def1, args.def2)

  return 0


if __name__ == '__main__':
  sys.exit(main())
