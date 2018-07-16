#!/usr/bin/env python
# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import json
import sys
import yaml


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('file')
  args = parser.parse_args()

  with open(args.file) as f:
    print json.dumps(yaml.load(f))


if __name__ == '__main__':
  sys.exit(main())
