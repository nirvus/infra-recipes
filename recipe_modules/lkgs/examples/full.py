# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'lkgs',
  'recipe_engine/path',
]


def RunSteps(api):
  api.lkgs.ensure_lkgs()
  assert api.lkgs.lkgs_tool

  api.lkgs(
      step_name='hello',
      builder='fuchsia/ci/garnet-x64-qemu_kvm',
      output_file=api.path['start_dir'].join('snapshot'),
  )


def GenTests(api):
  yield api.test('basic')
