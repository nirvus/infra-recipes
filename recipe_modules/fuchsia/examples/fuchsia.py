# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


TARGETS = ['arm64', 'x64']

BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

DEPS = [
  'infra/fuchsia',
  'infra/goma',
  'infra/swarming',
  'recipe_engine/json',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
]

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'build_type': Property(kind=Enum(*BUILD_TYPES),
                         help='The build type', default='debug'),
  'packages': Property(kind=List(basestring), help='Packages to build',
                       default=[]),
  'variants': Property(kind=List(basestring),
                      help='--variant arguments to gen.py', default=[]),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
  'ninja_targets': Property(kind=List(basestring),
                            help='Extra target args to pass to ninja',
                            default=[]),
  'run_tests': Property(kind=bool,
                        help='Whether to run tests or not',
                        default=False),
  'runtests_args': Property(kind=str,
                            help='Arguments to pass to the executable running tests',
                            default=''),
  'device_type': Property(kind=str,
                          help='The type of device to run tests on',
                          default='QEMU'),
  'snapshot_gcs_bucket': Property(kind=str,
                                  help='The GCS bucket to upload a jiri snapshot of the build'
                                       ' to. Will not upload a snapshot if this property is'
                                       ' blank or tryjob is True',
                                  default='fuchsia-snapshots'),
  'networking_for_tests': Property(kind=bool,
                                   help='Whether tests should have access to the network'
                                        ' (always False if tryjob is True or if device_type'
                                        ' != QEMU)',
                                   default=False),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, project, manifest,
             remote, target, build_type, packages, variants, gn_args,
             ninja_targets, run_tests, runtests_args, device_type,
             snapshot_gcs_bucket, networking_for_tests):
  checkout = api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      snapshot_gcs_bucket=snapshot_gcs_bucket,
  )
  assert checkout.root_dir
  assert checkout.snapshot_file
  assert checkout.snapshot_file_sha1

  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variants,
      gn_args=gn_args,
      ninja_targets=ninja_targets,
      test_cmds=['runtests' + runtests_args] if run_tests else None,
      test_device_type=device_type,
  )
  if run_tests:
    test_results = api.fuchsia.test(
        build=build, external_network=networking_for_tests)
    # Ensure failed_tests gets filled out when tests fail.
    if test_results.summary and test_results.failed_tests:
        assert test_results.failed_tests['/hello']
    # Ensure passed_tests gets filled out when tests pass.
    if test_results.summary and test_results.passed_tests:
        assert test_results.passed_tests['/hello']
    api.fuchsia.analyze_test_results('test results', test_results)

def GenTests(api):
  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests_x64') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data() + api.fuchsia.test_step_data()
  yield api.test('isolated_tests_x64_networking') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
      networking_for_tests=True,
  ) + api.fuchsia.task_step_data() + api.fuchsia.test_step_data()
  yield api.test('isolated_tests_arm64') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data() + api.fuchsia.test_step_data()
  yield api.test('isolated_tests_no_json') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data()
  yield api.test('isolated_tests_device') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      packages=['topaz/packages/default'],
      run_tests=True,
      device_type='NUC',
  ) + api.fuchsia.task_step_data(device=True) + api.fuchsia.test_step_data()
  yield api.test('isolated_tests_test_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data() + api.fuchsia.test_step_data(
      failure=True,
  ) + api.step_data('test results.symbolize', api.raw_io.stream_output('bt1\nbt2\n'))
  yield api.test('isolated_tests_task_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data(task_failure=True)
  yield api.test('isolated_tests_task_timed_out') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data(timed_out=True)
  yield api.test('isolated_tests_kernel_panic') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data(output='KERNEL PANIC')
  yield api.test('isolated_tests_infra_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data(infra_failure=True)

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  )
  yield api.test('garnet') + api.properties(
      project='garnet',
      manifest='manifest/garnet',
      remote='https://fuchsia.googlesource.com/garnet',
      target='x64',
      packages=['topaz/packages/default'],
  )
  yield api.test('peridot') + api.properties(
      manifest='peridot',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  )
  yield api.test('goma_local_cache') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      goma_local_cache=True,
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      build_type='release',
  )
  yield api.test('lto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      build_type='lto',
  )
  yield api.test('thinlto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      build_type='thinlto',
  )
  yield api.test('host_asan') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      variants=['host_asan'],
  )
  yield api.test('asan') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      packages=['topaz/packages/default'],
      variants=['host_asan', 'asan'],
  )
  yield api.test('cq') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
  yield api.test('ci_no_snapshot') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      snapshot_gcs_bucket=None,
  )
  yield api.test('cq_no_snapshot') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      tryjob=True,
      snapshot_gcs_bucket=None,
  )
  yield api.test('gn_args') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      tryjob=True,
      gn_args=['super_arg=false', 'less_super_arg=true'],
  )
  yield api.test('ninja_targets') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      tryjob=True,
      ninja_targets=['//target:one', '//target:two'],
  )
  yield api.test('manifest') + api.properties.tryserver(
      patch_project='manifest',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
