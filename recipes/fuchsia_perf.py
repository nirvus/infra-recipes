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

    # Each layer should have a Fuchsia package containing a single benchmarks.sh which
    # runs all benchmarks.  For more information, see the following documentation:
    # https://fuchsia.googlesource.com/docs/+/master/development/benchmarking/running_on_ci.md
    'benchmarks_package':
        Property(
            kind=str,
            help='The name of the package containing benchmarks.sh',
            default=None,
        ),

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
    'snapshot_gcs_bucket':
        Property(
            kind=str,
            help='The GCS bucket to upload a jiri snapshot of the build'
            ' to. Will not upload a snapshot if this property is'
            ' blank or tryjob is True',
            default='fuchsia-snapshots'),
}


def RunSteps(api, project, manifest, remote, target, build_type, packages,
             variant, gn_args, catapult_url, device_type,
             dashboard_masters_name, dashboard_bots_name, patch_ref,
             patch_gerrit_url, patch_project, snapshot_gcs_bucket,
             upload_to_dashboard, benchmarks_package):
  api.catapult.ensure_catapult()

  if api.properties.get('tryjob'):
    snapshot_gcs_bucket = None
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      snapshot_gcs_bucket=snapshot_gcs_bucket,
  )

  execution_timestamp_ms = api.time.ms_since_epoch()

  # TODO(kjharland): Specify benchmarks_package in existing configs and delete this.
  if not benchmarks_package:
    benchmarks_package = project + '_benchmarks'

  test_cmds = [
      '/pkgfs/packages/%s/0/bin/benchmarks.sh %s' % (
          benchmarks_package,
          api.fuchsia.results_dir_on_target,
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

  # Log the results of each benchmark.
  api.fuchsia.report_test_results(test_results)

  # Get the LUCI build log URL to attach to the perf data.  This might be empty
  # or None because of an infra failure.
  build_id = api.buildbucket.build_id

  # Although it's unusual, BuildBucketApi returns parsed JSON as the step
  # result's stdout.
  build_json = api.buildbucket.get_build(build_id).stdout
  log_url = build_json.get('build', {}).get('url', None)
  assert log_url, "Couldn't fetch info for build %s. BuildBucket API returned: %s" % (
      build_id, build_json)

  # Analyze all of the benchmarks that ran successfully
  for test_filepath, test_results in test_results.passed_tests.iteritems():
    # Extract the name of the test suite, e.g. "baz_test" in
    # "foo/bar/baz_test.json".
    test_suite, extension = api.path.splitext(api.path.basename(test_filepath))

    # Only look at files with a ".json" extension, which we take to be
    # Fuchsia perf test results files.  This allows the Fuchsia side to
    # output other file types -- in particular, Catapult Histogram files,
    # which we skip for now, but will later switch to using (see IN-444).
    if extension == '.json':
      # Prepend "fuchsia." to make test results easier to find in the
      # dashboard.
      dashboard_test_suite = "fuchsia." + test_suite

      ProcessTestResults(
          # Prevent corrupting the step name with extra dots.
          step_name="analyze_%s" % test_suite.replace('.', '_'),
          api=api,
          dashboard_masters_name=dashboard_masters_name,
          dashboard_bots_name=dashboard_bots_name,
          execution_timestamp_ms=execution_timestamp_ms,
          test_suite=dashboard_test_suite,
          test_results=test_results,
          catapult_url=catapult_url,
          upload_to_dashboard=upload_to_dashboard,
          log_url=log_url,
      )


def ProcessTestResults(api, step_name, dashboard_masters_name,
                       dashboard_bots_name, execution_timestamp_ms, test_suite,
                       test_results, catapult_url, upload_to_dashboard,
                       log_url):
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
    upload_to_dashboard (bool): Whether to upload results.
    log_url (str): Link to this build's log page.
  """
  with api.step.nest(step_name):
    # Generate the histogram set.
    histogram_output = api.catapult.make_histogram(
        input_file=api.raw_io.input_text(test_results),
        test_suite=test_suite,
        masters_name=dashboard_masters_name,
        bots_name=dashboard_bots_name,
        execution_timestamp_ms=execution_timestamp_ms,
        output_file=api.json.output(),
        log_url=log_url,
    ).json.output

    # Upload the file to Catapult using the current build's credentials.
    if upload_to_dashboard and not api.properties.get('tryjob'):
      api.catapult.upload(
          input_file=api.json.input(histogram_output), url=catapult_url)


def GenTests(api):
  # Example JSON summary.
  summary_json = api.json.dumps({
      "tests": [
          {
              "name": "passed.json",
              "output_file": "passed.json",
              "result": "PASS",
          },
          {
              # Include at least one benchmark that failed to make sure its
              # results are not analyzed and uploaded to Catapult.
              "name": "failed.json",
              "output_file": "failed.json",
              "result": "FAIL",
          }
      ]
  })
  # Dict representing the set of files and their contents that are downloaded from
  # the target device when tests/benchmarks are finished.
  extracted_results = {
      'summary.json': summary_json,
      'passed.json': '{"test_name": "a", "units": "b", "samples": [1, 2, 3]}',
      # No output for failed benchmark.
      'failed.json': '{}',
  }

  # Test API response for a call to the BuildBucket API's `get` method, which
  # Returns JSON information for a single build.  This information is only
  # fetched after test results are successfully copied off of the target device,
  # (otherwise the recipe fails before FuchsiaApi.test() exits) so tests that
  # fail at this point may omit it.
  #
  # TODO(kjharland): This should be amended upstream in BuildbucketTestApi.
  buildbucket_get_response = api.step_data(
      'buildbucket.get',
      stdout=api.raw_io.output_text(
          api.json.dumps({
              "build": {
                  "id": "123",
                  "status": "SCHEDULED",
                  "url": "https://ci.chromium.org/p/fuchsia/builds/b123",
                  "bucket": "luci.fuchsia.ci",
              }
          })))
  buildbucket_test_data = api.buildbucket.ci_build() + buildbucket_get_response

  # Test cases for running Fuchsia performance tests as a swarming task.
  yield api.test('successful_run') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
      benchmarks_package='topaz_benchmarks',
  ) + (
      buildbucket_test_data + api.fuchsia.task_step_data() + api.step_data(
          'extract results', api.raw_io.output_dir(extracted_results)))

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
  ) + (
      buildbucket_test_data + api.fuchsia.task_step_data() + api.step_data(
          'extract results', api.raw_io.output_dir(extracted_results)))

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
      dashboard_masters_name='fuchsia.try',
      dashboard_bots_name='topaz-builder',
      upload_to_dashboard=True,
      tryjob=True,
  ) + (
      buildbucket_test_data + api.fuchsia.task_step_data() + api.step_data(
          'extract results', api.raw_io.output_dir(extracted_results)))

  yield api.test('device_tests') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      device_type='Intel NUC Kit NUC6i3SYK',
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
  ) + (
      buildbucket_test_data +
      api.fuchsia.task_step_data(device=True) + api.step_data(
          'extract results', api.raw_io.output_dir(extracted_results)))

  yield api.test('missing test results') + api.properties(
      project='topaz',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      dashboard_masters_name='fuchsia.ci',
      dashboard_bots_name='topaz-builder',
  ) + (
      api.fuchsia.task_step_data() +
      api.step_data('extract results', api.raw_io.output_dir({})))
