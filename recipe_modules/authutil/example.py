# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine.types import freeze

DEPS = [
  'authutil',
  'recipe_engine/json',
  'recipe_engine/platform',
  'recipe_engine/properties',
]

PROPERTIES = {
  'scopes': Property(),
  'lifetime_sec': Property(),
}

BUILDERS = freeze({
  'mac': {
    'platform': ('mac', 64),
  },
  'linux': {
    'platform': ('linux', 64),
  },
})


def RunSteps(api, scopes, lifetime_sec):
  api.authutil.ensure_authutil()
  api.authutil.get_token('fake-account', scopes=scopes, lifetime_sec=lifetime_sec)


def GenTests(api):
  def props(scopes=None, lifetime_sec=None):
    return api.properties.generic(scopes=scopes, lifetime_sec=lifetime_sec)

  for buildername in BUILDERS:
    platform = BUILDERS[buildername].get('platform')
    yield (api.test(buildername) +
           props() +
           api.step_data('get access token',
                         api.json.output({'token': 'abc123', 'expiry': 123})) +
           api.platform(*platform))
    yield (api.test('%s_no_authutil' % buildername) +
           props() +
           api.step_data('get access token', retcode=1) +
           api.platform(*platform))
    yield (api.test(buildername + '_with_scopes') +
           props(scopes=['fake-scope']) +
           api.step_data('get access token',
                         api.json.output({'token': 'abc123', 'expiry': 123})) +
           api.platform(*platform))
    yield (api.test(buildername + '_with_lifetime_sec') +
           props(lifetime_sec=60) +
           api.step_data('get access token',
                         api.json.output({'token': 'abc123', 'expiry': 123})) +
           api.platform(*platform))
