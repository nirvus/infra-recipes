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
    'patch_gerrit_url':
        Property(kind=str, help='Gerrit host', default=None),
    'patch_project':
        Property(kind=str, help='Gerrit project', default=None),
    'patch_ref':
        Property(kind=str, help='Gerrit patch ref', default=None),
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

    # Performance dashboard information.
    #
    # These values are the search terms that will be used when finding graphs in
    # the Catapult dashboard. TODO(IN-336): Link to docs once they're public.
    #
    # Explicitly passing these values prevents BuildBucketApi changes, builder
    # renames, or other unexpected changes from affecting the data in the
    # dashboard.
    'dashboard_masters_name':
        Property(
            kind=str,
            help='The name of the "masters" field in the performance dashboard'
        ),
    'dashboard_bots_name':
        Property(
            kind=str,
            help='The name of the "bots" field in the performance dashboard'),
    'upload_to_dashboard':
        Property(
            kind=bool,
            help=
            'Whether to upload benchmark results. Make sure you set this to false when testing',
            default=True),
}


def RunSteps(api, project, manifest, remote, target, build_type, packages,
             variant, gn_args, catapult_url, device_type,
             dashboard_masters_name, dashboard_bots_name, patch_ref,
             patch_gerrit_url, patch_project, upload_to_dashboard):

  api.catapult.ensure_catapult()
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
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

  # Skip summary.json, which is a sort of manifest of tests results, and is
  # required by botanist to decide which files should be copied off the
  # Fuchsia device after testing.  Today, fuchsia_perf does not need this
  # file.
  test_results.outputs.pop('summary.json', None)

  for filepath in test_results.outputs:
    test_results_contents = test_results.outputs[filepath]
    # Extract the name of the test suite, e.g. "baz_test" in
    # "foo/bar/baz_test.json".
    test_suite = api.path.splitext(api.path.basename(filepath))[0]
    # Prepend "fuchsia." to make test results easier to find in the
    # dashboard.
    dashboard_test_suite = "fuchsia." + test_suite

    ProcessTestResults(
        step_name="analyze_%s" % test_suite,
        api=api,
        dashboard_masters_name=dashboard_masters_name,
        dashboard_bots_name=dashboard_bots_name,
        test_suite=dashboard_test_suite,
        test_results=test_results_contents,
        catapult_url=catapult_url,
        upload_to_dashboard=upload_to_dashboard,
    )


def ProcessTestResults(api, step_name, dashboard_masters_name,
                       dashboard_bots_name, test_suite, test_results,
                       catapult_url, upload_to_dashboard):
  """
  Processes test results and uploads them to the Catapult dashboard.

  Args:
    step_name (str): The name of the step under which to test the processing
      steps.
    dashboard_masters_name (str): The masters name to use in the perf dashboard.
    dashboard_bots_name (str): The bots name to use in the perf dashboard.
    test_suite (str): The name of the test suite that was run.
    test_results (str): The raw test results output.
    catapult_url (str): The URL of the catapult dashboard.
  """
  with api.step.nest(step_name):
    # Generate the histogram set.
    histogram_output = api.catapult.make_histogram(
        input_file=api.raw_io.input_text(test_results),
        test_suite=test_suite,
        masters_name=dashboard_masters_name,
        bots_name=dashboard_bots_name,
        execution_timestamp_ms=api.time.ms_since_epoch(),
        output_file=api.json.output(),
    ).json.output

    # Upload the file to Catapult using the current build's credentials.
    if upload_to_dashboard and not api.properties.get('tryjob'):
      api.catapult.upload(
          input_file=api.json.input(histogram_output), url=catapult_url)


def GenTests(api):
  # Test cases for running Fuchsia performance tests as a swarming task.
  yield api.test('successful_run') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
  ) + api.fuchsia.task_step_data() + api.step_data(
      'extract results',
      api.raw_io.output_dir({
          '/path/to/zircon_benchmarks.json': 'I am a benchmark, ha ha!',
      }))

  # Tests running this recipe with a pending Gerrit change. Note
  # that upload_to_dashboard is false. Be sure to set this when
  # testing patches.
  yield api.test('with_patch') + api.properties(
      patch_project='garnet',
      patch_ref='refs/changes/96/147496/10',
      patch_gerrit_url='https://fuchsia-review.googlesource.com',
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
      upload_to_dashboard=False,
  ) + api.fuchsia.task_step_data() + api.step_data(
      'extract results',
      api.raw_io.output_dir({
          'summary.json': 'I summarize test results!',
          'zircon_benchmarks.json': 'I am a benchmark, ha ha!',
      }))

  # CQ runs should disable certain things like dashboard uploads.
  yield api.test('cq') + api.properties(
      patch_project='garnet',
      patch_ref='refs/changes/96/147496/10',
      patch_gerrit_url='https://fuchsia-review.googlesource.com',
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
      upload_to_dashboard=True,
      tryjob=True,
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
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
  ) + api.fuchsia.task_step_data(device=True) + api.step_data(
      'extract results',
      api.raw_io.output_dir({
          'summary.json': 'I summarize test results!',
          'zircon_benchmarks.json': 'I am a benchmark, ha ha!',
      }))

  yield api.test('missing test results') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
  ) + api.fuchsia.task_step_data() + api.step_data('extract results',
                                                   api.raw_io.output_dir({}))
