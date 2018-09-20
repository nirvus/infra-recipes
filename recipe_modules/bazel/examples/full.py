# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'bazel',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
    'tar',
]

PROPERTIES = {
    'bazel_version': Property(kind=str, default=None),
}


def RunSteps(api, bazel_version):
  # Ensure that bazel is installed.
  # If the version is "None", call it without any params to test the
  # default behavior.
  ensure_args = {}
  if bazel_version is not None:
    ensure_args['version'] = bazel_version
  bazel_path = api.bazel.ensure_bazel(**ensure_args)
  assert api.path.basename(bazel_path) == 'bazel'

  # Calling it again with the same version should be a no-op and should return
  # the same path.
  bp2 = api.bazel.ensure_bazel(**ensure_args)
  assert bp2 == bazel_path, '%s != %s' % (bp2, bazel_path)

  # None and 'latest' should be the same.
  if bazel_version == 'latest':
    bp3 = api.bazel.ensure_bazel()  # Try the default.
    assert bp3 == bazel_path, '%s != %s' % (bp3, bazel_path)
  elif bazel_version is None:
    bp4 = api.bazel.ensure_bazel(version='latest')
    assert bp4 == bazel_path, '%s != %s' % (bp4, bazel_path)

  # Not ok to re-ensure with a different version.
  other_version = str(bazel_version) + '-other'
  saw_assertion = False
  try:
    api.bazel.ensure_bazel(version=other_version)
  except AssertionError as e:
    saw_assertion = True  # Expected
  assert saw_assertion, 'Should have failed to ensure different version'


def GenTests(api):
  for platform in ('linux', 'mac'):
    for bazel_version in (None, 'latest', '0.1.2'):
      test_name = platform + '_version_' + str(bazel_version)
      yield api.test(test_name) + api.platform.name(platform) + api.properties(
          bazel_version=bazel_version)
