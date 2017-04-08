# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class ServiceAccountApi(recipe_api.RecipeApi):
  """ServiceAccountApi provides access to service account keys."""

  def __init__(self, *args, **kwargs):
    super(ServiceAccountApi, self).__init__(*args, **kwargs)

  def _config_defaults(self):
    self.set_config('service_account_default')

  def get_json_path(self, account):
    if self.c is None: # pragma: no cover
      return None
    return self.m.path.join(self.c.accounts_path,
                            'service-account-%s.json' % account)
