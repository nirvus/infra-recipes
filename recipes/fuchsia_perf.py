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

DEVICES = ['QEMU', 'Intel NUC Kit NUC6i3SYK', 'Intel NUC Kit NUC7i5DNHE']

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
    'ninja_targets':
        Property(
            kind=List(basestring),
            help='Extra target args to pass to ninja',
            default=[]),
    'boards':
        Property(kind=List(basestring), help='Boards to build', default=[]),
    'products':
        Property(kind=List(basestring), help='Products to build', default=[]),
    'test_pool':
        Property(
            kind=str,
            help='Swarming pool from which a test task will be drawn',
            default='fuchsia.tests'),
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
    'pave':
        Property(
            kind=bool,
            help='Whether to pave images the device for testing. (Ignored if'
            ' device_type == QEMU)',
            default=True),

    # Each layer should have a Fuchsia package containing a single benchmarks.sh which
    # runs all benchmarks.  For more information, see the following documentation:
    # https://fuchsia.googlesource.com/docs/+/master/development/benchmarking/running_on_ci.md
    'benchmarks_package':
        Property(
            kind=str, help='The name of the package containing benchmarks.sh'),

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
    'test_timeout_secs':
        Property(
            kind=int,
            help='How long to wait until timing out on tests',
            default=40 * 60),
}


def RunSteps(api, project, manifest, remote, target, build_type, packages,
             variant, gn_args, ninja_targets, test_pool, catapult_url,
             device_type, pave, dashboard_masters_name, dashboard_bots_name,
             upload_to_dashboard, benchmarks_package, boards, products, test_timeout_secs):
  api.catapult.ensure_catapult()

  api.fuchsia.checkout(
      build=api.buildbucket.build,
      manifest=manifest,
      remote=remote,
      project=project,
  )

  execution_timestamp_ms = api.time.ms_since_epoch()

  # Get the LUCI build log URL to attach to the perf data.  This might be empty
  # or None because of an infra failure.
  build_id = api.buildbucket.build_id

  # Although it's unusual, BuildBucketApi returns parsed JSON as the step
  # result's stdout.
  build_json = api.buildbucket.get_build(build_id).stdout
  log_url = build_json.get('build', {}).get('url', None)
  assert log_url, "Couldn't fetch info for build %s. BuildBucket API returned: %s" % (
      build_id, build_json)

  # yapf: disable
  test_cmds = [
      ' '.join(['/pkgfs/packages/%s/0/bin/benchmarks.sh' % benchmarks_package,
                api.fuchsia.results_dir_on_target,
                '--catapult-converter-args',
                '--bots', dashboard_bots_name,
                '--masters', dashboard_masters_name,
                '--execution-timestamp-ms', '%d' % execution_timestamp_ms,
                '--log-url', log_url])
  ]
  # yapf: enable

  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      ninja_targets=ninja_targets,
      boards=boards,
      products=products,
      build_for_testing=True,
  )
  test_results = api.fuchsia.test(
      build=build,
      test_pool=test_pool,
      timeout_secs=test_timeout_secs,
      pave=pave,
      test_cmds=test_cmds,
      device_type=device_type,
  )

  # Log the results of each benchmark.
  api.fuchsia.report_test_results(test_results)

  # Upload results for all of the benchmarks that ran successfully.
  for test_filepath, file_data in test_results.passed_test_outputs.iteritems():
    step_name = 'upload %s' % api.path.basename(test_filepath)
    _, extension = api.path.splitext(api.path.basename(test_filepath))

    # Only look at the Catapult HistogramSet JSON files.
    #
    # The other files are the raw Fuchsia perf test results files (in
    # JSON format), which are returned as test results so that they
    # get archived, but which we skip here.
    if (extension == '.catapult_json' and not api.properties.get('tryjob') and
        upload_to_dashboard):
      with api.step.nest(step_name):
        api.catapult.upload(
            input_file=api.raw_io.input_text(file_data), url=catapult_url, timeout='60s')

  # Fail if any benchmarks failed.
  if len(test_results.failed_test_outputs) > 0:
    raise api.step.StepFailure(
        "The following benchmarks failed. "
        "See kernel log and individual steps for details: %s" %
        test_results.failed_test_outputs.keys())


def GenTests(api):
  # Test API response for a call to the BuildBucket API's `get` method, which
  # Returns JSON information for a single build.
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

  # Test cases for running Fuchsia performance tests as a swarming task.
  yield api.fuchsia.test(
      'successful_run',
      properties=dict(
        dashboard_masters_name='fuchsia.ci',
        dashboard_bots_name='topaz-builder',
        benchmarks_package='topaz_benchmarks',
        run_tests=True,
      ),
      steps=[
        buildbucket_get_response,
      ],
    )

  yield api.fuchsia.test(
      'failed_run',
      properties=dict(
        dashboard_masters_name='fuchsia.ci',
        dashboard_bots_name='topaz-builder',
        benchmarks_package='topaz_benchmarks',
        run_tests=True,
      ),
      steps=[
        buildbucket_get_response,
        api.fuchsia.test_step_data(failure=True),
      ],
    )

  # Tests running this recipe with a pending Gerrit change. Note
  # that upload_to_dashboard is false. Be sure to set this when
  # testing patches.
  yield api.fuchsia.test(
      'with_patch',
      tryjob=True,
      properties=dict(
        run_tests=True,
        upload_to_dashboard=False,
        dashboard_masters_name='fuchsia.try',
        dashboard_bots_name='topaz-builder',
        benchmarks_package='topaz_benchmarks',
      ),
      steps=[
        buildbucket_get_response,
      ],
    )

  yield api.fuchsia.test(
      'device_tests',
      properties=dict(
          dashboard_masters_name='fuchsia.ci',
          dashboard_bots_name='topaz-builder',
          benchmarks_package='topaz_benchmarks',
          run_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
      ),
      steps=[
        buildbucket_get_response,
      ],
  )

  yield api.fuchsia.test(
      'missing_test_results',
      properties=dict(
          dashboard_masters_name='fuchsia.ci',
          dashboard_bots_name='topaz-builder',
          benchmarks_package='topaz_benchmarks',
          run_tests=True,
      ),
      steps=[
        buildbucket_get_response,
        api.step_data('extract results', api.raw_io.output_dir({})),
      ],
  )
