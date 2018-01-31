# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


TARGETS = ['arm64', 'x86-64']

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
  'run_tests': Property(kind=bool,
                        help='Whether to run tests or not',
                        default=False),
  'runtests_args': Property(kind=str,
                            help='Arguments to pass to the executable running tests',
                            default=''),
  'upload_snapshot': Property(kind=bool,
                          help='Whether to upload jiri snapshot (always False if tryjob is true)',
                          default=True),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, project, manifest,
             remote, target, build_type, packages, variants, gn_args, run_tests,
             runtests_args, upload_snapshot):
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      upload_snapshot=upload_snapshot,
  )
  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variants,
      gn_args=gn_args,
      test_cmds=['runtests' + runtests_args] if run_tests else None,
  )
  if run_tests:
    api.fuchsia.test(build)


def GenTests(api):
  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests_x86') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  ))
  yield api.test('isolated_tests_arm64') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='arm64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  ))
  yield api.test('isolated_tests_test_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  )) + api.step_data('read test summary', api.json.output({
      'tests': [{'name': '/hello', 'result': 'FAIL'}],
  })) + api.step_data('symbolize', api.raw_io.stream_output('bt1\nbt2\n'))
  yield api.test('isolated_tests_task_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      task_failure=True,
  ))
  yield api.test('isolated_tests_task_timed_out') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      timed_out=True,
  ))
  yield api.test('isolated_tests_kernel_panic') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      output='ZIRCON KERNEL PANIC',
      outputs=['test.fs'],
      task_failure=True,
  ))
  yield api.test('isolated_tests_infra_failure') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
      infra_failure=True,
  ))

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('garnet') + api.properties(
      project='garnet',
      manifest='manifest/garnet',
      remote='https://fuchsia.googlesource.com/garnet',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('peridot') + api.properties(
      manifest='peridot',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('no_goma') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      goma_dir='/path/to/goma',
  )
  yield api.test('goma_local_cache') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      goma_local_cache=True,
  )
  yield api.test('release') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      build_type='release',
  )
  yield api.test('lto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      build_type='lto',
  )
  yield api.test('thinlto') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      build_type='thinlto',
  )
  yield api.test('host_asan') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
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
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
  yield api.test('cq_no_snapshot') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
      upload_snapshot=False,
  )
  yield api.test('gn_args') + api.properties.tryserver(
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
      gn_args=['super_arg=false', 'less_super_arg=true'],
  )
  yield api.test('manifest') + api.properties.tryserver(
      patch_project='manifest',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      patch_ref='refs/changes/23/123/12',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
