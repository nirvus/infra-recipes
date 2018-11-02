# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
import collections

DEPS = [
    'infra/checkout',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/path',
]

PROPERTIES = {
    'project':
        Property(kind=str, help='The git project', default='garnet'),
    'override':
        Property(kind=bool, help='Whether to override $project', default=False),
}


def RunSteps(api, project, override):
  api.checkout(
      manifest='minimal',
      remote='https://fuchsia.googlesource.com/manifest',
      project=project,
      build_input=api.buildbucket.build.input,
      override=override,
  )


def GenTests(api):
  yield api.checkout.test(
      'global integration tryjob',
      project='integration',
      override=False,
      tryjob=True,
  )

  yield api.checkout.test(
      'global integration ci',
      project='integration',
      override=False,
      tryjob=False,
  )

  yield api.checkout.test(
      'local integration tryjob',
      project='garnet',
      override=True,
      tryjob=True,
  )

  yield api.checkout.test(
      'local integration ci',
      project='garnet',
      override=True,
      tryjob=False,
  )

  yield api.checkout.test(
      'tryjob_with_patchfile',
      project='garnet',
      tryjob=True,
      patchfile=[{
          'ref': 'refs/changes/cc/aabbcc/1',
          'host': 'example-review.googlesource.com',
          'project': 'not_garnet'
      }])

  yield api.checkout.test(
      'fail_to_patch_over_gerrit_change',
      project='garnet',
      tryjob=True,
      patchfile=[{
          'ref': 'refs/changes/cc/aabbcc/1',
          'host': 'fuchsia-review.googlesource.com',
          'project': 'garnet',
      }])

  yield api.checkout.test(
      'fail_to_patch_same_project_many_times',
      project='garnet',
      tryjob=True,
      patchfile=[{
          'ref': 'refs/changes/cc/aabbcc/1',
          'host': 'fuchsia-review.googlesource.com',
          'project': 'zircon',
      }, {
          'ref': 'refs/changes/ff/ddeeff/2',
          'host': 'fuchsia-review.googlesource.com',
          'project': 'zircon',
      }])
