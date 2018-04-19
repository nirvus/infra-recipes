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

DEVICES = ['QEMU', 'Intel NUC Kit NUC6i3SYK']

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
            help='--variant arguments to GN in `select_variant`',
            default=[]),
    'gn_args':
        Property(
            kind=List(basestring), help='Extra args to pass to GN', default=[]),
    'catapult_url':
        Property(
            kind=str,
            help='Catapult dashboard URL',
            default=DEFAULT_CATAPULT_URL),
    'device_type':
        Property(
            kind=Enum(*DEVICES),
            help='The type of device to execute tests on, if the value is'
            ' not QEMU it will be passed to Swarming as the device_type'
            ' dimension',
            default='QEMU'),
}


def RunSteps(api, project, manifest, remote, target, build_type, packages,
             variant, gn_args, catapult_url, device_type):
  api.catapult.ensure_catapult()
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
  )

  # Each project should have a Fuchsia package named ${project}_benchmarks
  # containing a single script called "benchamrks.sh" that runs all benchmarks
  # in the project.  Its only argument should be the directory where output is
  # written.
  #
  # TODO(IN-197): Add link to documentation explaining why and how this works.
  test_cmds = [
      '/pkgfs/packages/%s_benchmarks/0/bin/benchmarks.sh %s' % (
          project,
          api.fuchsia.target_test_dir(),
      )
  ]

  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      test_cmds=test_cmds,
      test_device_type=device_type,
  )
  test_results = api.fuchsia.test(build)

  # Get build information.
  #
  # NOTE: It's important that these names do not contain '/'. That is a
  # signficant character to the Catapult dashboard, which will fail to correctly
  # index the data.
  builder_id = api.buildbucket.builder_id
  builder = builder_id.builder
  project = builder_id.project
  # The usual "luci.fuchsia.ci" bucket name no longer includes the prefix
  # "luci.{project}" in BuildBucket API v2.  Prepend the project name to make
  # the bucket name unique to Fuchsia in the perf dashboard. It shows up as
  # "fuchsia.ci" or "fuchsia.try", etc... depending on the bucket name.
  bucket = "%s.%s" % (project, builder_id.bucket)

  # On a local workstation, builder_id properties are not set. Use test values.
  #
  # Since we can't mock the case where builder_id properties *are* set (The code
  # would never enter the block `if builder_id.bucket` and recipes complains
  # about missing coverage for those lines) always read the real-values above
  # first, then do this if-check.
  #
  # TODO(kjharland): Make BuildBucketTestApi.builder_id testable.
  if not project:
    project = 'fuchia'
    builder = 'example.builder'
    bucket = 'fuchsia.example.bucket'

  for filename in test_results.outputs:
    # strip file suffix
    test_results_contents = test_results.outputs[filename]
    test_name = api.path.splitext(filename)[0]

    ProcessTestResults(
        step_name="analyze_%s" % test_name,
        api=api,
        bucket=bucket,
        builder=builder,
        test_suite=test_name,
        test_results=test_results_contents,
        catapult_url=catapult_url,
    )


def ProcessTestResults(api, step_name, bucket, builder, test_suite,
                       test_results, catapult_url):
  """
  Processes test results and uploads them to the Catapult dashboard.

  Args:
    step_name (str): The name of the step under which to test the processing
      steps.
    bucket (str): The bucket name to use in the perf dashboard.
    builder (str): The builder name to use in the perf dashboard.
    test_suite (str): The name of the test suite that was run.
    test_results (str): The raw test results output.
    catapult_url (str): The URL of the catapult dashboard.
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
  yield api.test('run_all_tests') + api.properties(
      project='garnet',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['garnet/packages/kitchen_sink'],
  ) + api.fuchsia.task_step_data() + api.step_data(
      'extract results',
      api.raw_io.output_dir({
          'zircon_benchmarks.json': '[ZIRCON_BENCHMARKS_RESULTS]',
          'ledger_benchmark.json': '[LEDGER_BENCHMARKS_RESULTS]',
      }))

  # Test cases for running Fuchsia performance tests as a swarming task.
  yield api.test('successful_run') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  ) + api.fuchsia.task_step_data() + api.step_data(
      'extract results',
      api.raw_io.output_dir({
          'zircon_benchmarks.json': 'I am a benchmark, ha ha!',
      }))

  yield api.test('device_tests') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      device_type='Intel NUC Kit NUC6i3SYK',
  ) + api.fuchsia.task_step_data(device=True) + api.step_data(
      'extract results',
      api.raw_io.output_dir({
          'zircon_benchmarks.json': 'I am a benchmark, ha ha!',
      }))

  yield api.test('missing test results') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  ) + api.fuchsia.task_step_data() + api.step_data('extract results',
                                                   api.raw_io.output_dir({}))
