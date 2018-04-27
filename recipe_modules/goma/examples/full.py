# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'goma',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/step',
]


def RunSteps(api):
  api.goma.ensure_goma()
  api.goma.ensure_goma(canary=True)
  api.step('gn', ['gn', 'gen', 'out/Release',
                  '--args=use_goma=true goma_dir=%s' % api.goma.goma_dir])

  with api.goma.build_with_goma(env={}):
    # build something using goma.
    api.step('echo goma jobs',
             ['echo', str(api.goma.recommended_goma_jobs)])
    api.step('echo goma jobs second',
             ['echo', str(api.goma.recommended_goma_jobs)])


def GenTests(api):
  for platform in ('linux', 'mac'):
    properties = {
        'buildername': 'test_builder',
        'path_config': 'swarmbucket',
        'luci_context': '/b/s/w/itOi5hUE/luci_context.475597099',
    }

    yield (api.test(platform) + api.platform.name(platform) +
           api.properties.generic(**properties))
