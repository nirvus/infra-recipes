# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
import collections

DEPS = [
    'infra/checkout',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
]

PROPERTIES = {
    'project':
        Property(kind=str, help='The git project', default='garnet'),
    'override':
        Property(kind=bool, help='Whether to override $project', default=False),
}


def RunSteps(api, project, override):
  build = api.buildbucket.build

  api.checkout(
      manifest='minimal',
      remote='https://fuchsia.googlesource.com/manifest',
      project=project,
      build_input=build.input,
      override=override,
  )


def GenTests(api):
  #yapf:disable
  yield (api.test('global integration tryjob') + api.properties(
      project='integration',
      override=False,
      **api.checkout.buildbucket_properties(project='integration',
                                            tryjob=True)))

  yield (api.test('global integration ci') + api.properties(
      project='integration',
      override=False,
      **api.checkout.buildbucket_properties(project='integration',
                                            tryjob=False)))

  yield (api.test('local integration tryjob') + api.properties(
      override=True,
      **api.checkout.buildbucket_properties(tryjob=True)))

  yield (api.test('local integration ci') + api.properties(
      project='garnet',
      override=True,
      **api.checkout.buildbucket_properties(tryjob=False)))
  #yapf:enable