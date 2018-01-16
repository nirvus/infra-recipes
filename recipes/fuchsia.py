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
  'infra/swarming',
  'recipe_engine/properties',
]

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'build_type': Property(kind=Enum(*BUILD_TYPES),
                         help='The build type', default='debug'),
  'packages': Property(kind=List(basestring), help='Packages to build',
                       default=[]),
  # TODO(mknyszek): Rename to 'variants' since this property is a list.
  'variant': Property(kind=List(basestring),
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


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target, build_type, packages, variant, gn_args, run_tests, runtests_args,
             upload_snapshot):
  if api.properties.get('tryjob'):
    upload_snapshot = False
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
      variants=variant,
      gn_args=gn_args,
      include_tests=run_tests,
      runtests_args=runtests_args,
  )
  if run_tests:
    api.fuchsia.test(build)


def GenTests(api):
  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect_result(
      outputs=['test.fs'],
  ))

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
  )
  yield api.test('staging') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      upload_snapshot=False,
  )
  yield api.test('cq') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86-64',
      packages=['topaz/packages/default'],
      tryjob=True,
  )
