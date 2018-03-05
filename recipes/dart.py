# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Builds the Fuchsia Dart test image and runs the Dart tests."""

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/fuchsia',
  'infra/swarming',
  'recipe_engine/properties',
]

TARGETS = ['arm64', 'x64']

# To avoid having multiple codepaths in the fuchsia recipe module, we write a
# summary JSON file in the same structure as one produced by runtests, except
# only containing one test.
# TODO(mknyszek): Figure out a solution that lets us enumerate dart tests.
TESTS_PASSED = '{"tests": [{"name": "dart", "result": "PASS"}]}'
TESTS_FAILED = '{"tests": [{"name": "dart", "result": "FAIL"}]}'

PROPERTIES = {
  'manifest': Property(kind=str, help='Jiri manifest to use',
                       default='manifest/topaz'),
  'remote': Property(kind=str, help='Remote manifest repository',
                     default='https://fuchsia.googlesource.com/topaz'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build',
                     default='x64'),
  'build_type': Property(kind=Enum('debug', 'release'),
                         help='The build type', default='debug'),
}


def RunSteps(api, manifest, remote, target, build_type):
  api.fuchsia.checkout(manifest, remote)
  target_test_file = api.fuchsia.target_test_dir() + '/summary.json'
  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=['topaz/packages/default'],
      gn_args=['extra_bootdata = [ "//third_party/dart:dart_test_bootfs" ]'],
      test_cmds=[
        'cd /system/test/dart',
        # Print a different message depending on whether the test command passes
        # or fails. This is necessary because Dart tests are silent when they pass.
        # TODO(mknyszek): Make this much cleaner by writing out a file in the
        # tests instead of using redirects.
        'dart --checked tools/testing/dart/main.dart --progress=line -m %s -a x64 -r vm vm'
        '> /test/dart.out && echo %s > %s || echo %s > %s' % (
            build_type, TESTS_PASSED, target_test_file, TESTS_FAILED, target_test_file),
      ],
  )
  api.fuchsia.analyze_test_results('test results', api.fuchsia.test(build))


def GenTests(api):
  # TODO(mknyszek): Factor out api.swarming.collect() here into a
  # method of the fuchsia recipe module's test API, that way we could do
  # something like "api.fuchsia.test_result()" instead, and not have to depend
  # on the swarming recipe module.

  # Test with all the defaults.
  yield (api.test('basic') +
      api.step_data('collect', api.swarming.collect(
      outputs=['output.fs'],
    ))
  )

  # Test a release build.
  yield (api.test('release') +
    api.properties(build_type='release') +
    api.step_data('collect', api.swarming.collect(
      outputs=['output.fs'],
    ))
  )

