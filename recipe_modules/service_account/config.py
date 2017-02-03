# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.config import config_item_context, ConfigGroup
from recipe_engine.config import Single


def BaseConfig():
  return ConfigGroup(accounts_path = Single(str, required=True))


config_ctx = config_item_context(BaseConfig)


@config_ctx()
def service_account_default(c):
  c.accounts_path =  '/creds/service_accounts'
