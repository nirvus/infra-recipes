# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building Fuchsia and running performance tests.

This differs from the fuchsia recipe in the following ways:
* Performance Tests are run instead of unit tests.
* Tests are always run (this recipe is not used to verify builds).
* Test results are uploaded to the catapult dashboard after execution.
"""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re

TARGETS = ['arm64', 'x64']

BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

DEPS = [
    'infra/fuchsia',
    'infra/swarming',
    'recipe_engine/properties',
]

PROPERTIES = {
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
    'target':
        Property(kind=Enum(*TARGETS), help='Target to build'),
    'build_type':
        Property(
            kind=Enum(*BUILD_TYPES), help='The build type', default='debug'),
    'packages':
        Property(kind=List(basestring), help='Packages to build', default=[]),
    # TODO(mknyszek): Rename to 'variants' since this property is a list.
    'variant':
        Property(
            kind=List(basestring),
            help='--variant arguments to gen.py',
            default=[]),
    'gn_args':
        Property(
            kind=List(basestring), help='Extra args to pass to GN', default=[]),
    'runtests_args':
        Property(
            kind=str,
            help='Arguments to pass to the executable running tests',
            default=''),
}


def RunSteps(api, project, manifest, remote, target, build_type, packages,
             variant, gn_args, runtests_args):
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
  )

  # TODO(kjharland): Hardcoding perf-test suite binaries is fine for now. If the
  # number of suites explodes then we should look for an approach that doesn't
  # involve editing this recipe by hand each time.
  test_cmds = [
      '/system/test/perf/run_zircon_benchmarks.sh %s/zircon_benchmarks.json' % api.fuchsia.target_test_dir(),
  ]

  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      test_cmds=test_cmds,
  )

  api.fuchsia.test(build)
  # TODO(kjharland): Read minfs image, convert results, upload to catapult.

def GenTests(api):
  # Test cases for running Fuchsia performance tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  ) + api.step_data('collect', api.swarming.collect(outputs=['output.fs'],))
