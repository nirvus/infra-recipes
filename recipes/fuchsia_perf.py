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

DEFAULT_CATAPULT_URL = 'https://chromeperf.appspot.com'

BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

DEPS = [
    'infra/catapult',
    'infra/fuchsia',
    'infra/minfs',
    'infra/swarming',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
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
    'catapult_url':
        Property(
            kind=str,
            help='Catapult dashboard URL',
            default=DEFAULT_CATAPULT_URL),
}


def RunSteps(api, project, manifest, remote, target, build_type, packages,
             variant, gn_args, catapult_url):
  api.catapult.ensure_catapult()
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
  )

  zircon_test_output_filename = 'zircon_benchmarks.json'

  # TODO(kjharland): Hardcoding perf-test suite binaries is fine for now. If the
  # number of suites explodes then we should look for an approach that doesn't
  # involve editing this recipe by hand each time.
  test_cmds = [
      '/system/test/perf/run_zircon_benchmarks %s/%s' % (
          api.fuchsia.target_test_dir(),
          zircon_test_output_filename,
      )
  ]

  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      test_cmds=test_cmds,
  )

  test_results = api.fuchsia.test(build)

  # Skip analysis steps if our test output is missing. This avoids masking a system
  # failure with an obscure and unrelated error later on.
  if zircon_test_output_filename not in test_results.outputs:
    raise api.step.StepFailure(
        'Missing test output file %s. see kernel log for details. Found files %s'
        % (
            zircon_test_output_filename,
            list(test_results.outputs.keys()),
        ))

  # Get build information.
  #
  # WARNING: DO NOT use '/' in any of these names. Catapult creates a database
  # key from these names and each component of the key is separated by a '/'.
  # Using '/' in the names breaks this scheme and causes information in the
  # dashboard to render incorrectly.
  #
  # Default to example info when running locally.
  builder_id = api.buildbucket.builder_id
  # Use $project/$bucket as the bucket name because in Buildbucket v2 the bucket
  # name does not contain the luci.{project} prefix. Names like luci.fuchsia.ci
  # will be read here as 'ci'.  If the catapult dashboard UI changes, a name as
  # non-descript as 'ci' might become clobbered with some other team's 'ci'
  # bucket.
  project = builder_id.project or 'fuchsia'
  bucket = project + "." + (builder_id.bucket or 'example.bucket')

  builder = builder_id.builder or 'fuchsia.example.builder'

  ProcessTestResults(
      api=api,
      step_name="analyze_zircon_benchmarks",
      bucket=bucket,
      builder=builder,
      test_suite="zircon_benchmarks",
      test_results=test_results.outputs[zircon_test_output_filename],
      catapult_url=catapult_url,
  )


def ProcessTestResults(api, step_name, bucket, builder, test_suite,
                       test_results, catapult_url):
  """
  Processes test results and uploads them to the Catapult dashboard.

  Args:
    step_name (str): The name of the step under which to test the processing
      steps.
    test_suite (str): The name of the test suite that was run.
    test_results (str): The raw test results output.
  """
  with api.step.nest(step_name):
    hs_filepath = api.path['start_dir'].join('histogram_set.json')

    # Create a Placeholder for histogram set data.  The
    # placeholder is backed by a file which is referenced as
    # placeholder.backing_file.
    hs_placeholder = api.json.output(leak_to=hs_filepath)

    # Generate the histogram set.
    api.catapult.make_histogram(
        input_file=api.raw_io.input_text(test_results),
        test_suite=test_suite,
        builder=builder,
        bucket=bucket,
        datetime=api.time.ms_since_epoch(),
        stdout=hs_placeholder,
    )

    # Upload the file to Catapult using the current build's credentials.
    # Use the path to the backing file for testing, since the placeholder's
    # backing file property is `None` in a test.
    api.catapult.upload(
        input_file=hs_placeholder.backing_file or hs_filepath,
        url=catapult_url,
    )


def GenTests(api):
  # Test cases for running Fuchsia performance tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  ) + api.step_data(
      'collect', api.swarming.collect(outputs=['output.fs'],)) + api.step_data(
          'extract results',
          api.raw_io.output_dir({
              'zircon_benchmarks.json': 'I am a benchmark, ha ha!',
          }))
  yield api.test('missing test results') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  ) + api.step_data(
      'collect', api.swarming.collect(outputs=['output.fs'],)) + api.step_data(
          'extract results',
          api.raw_io.output_dir({
              'not_zircon_benchmarks.json': 'No one cares about this data',
          }))
