# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class AuthutilApi(recipe_api.RecipeApi):
  """AuthutilApi allows generating OAuth2 tokens from locally stored secrets.

  This is a thin wrapper over the authutil go executable, which itself calls
  https://github.com/luci/luci-go/blob/master/client/authcli/authcli.go
  """

  def __init__(self, *args, **kwargs):
    super(AuthutilApi, self).__init__(*args, **kwargs)
    self._authutil_path = None

  def ensure_authutil(self, version=None):
    with self.m.step.nest('ensure_authutil'):
      with self.m.step.context({'infra_step': True}):
        authutil_package = ('infra/tools/authutil/%s' %
            self.m.cipd.platform_suffix())
        authutil_dir = self.m.path['start_dir'].join('cipd', 'authutil')

        self.m.cipd.ensure(
            authutil_dir, {authutil_package: version or 'latest'})
        self._authutil_path = authutil_dir.join('authutil')

        return self._authutil_path

  def get_token(self, account, scopes=None, lifetime_sec=None):
    assert self._authutil_path

    account_file = self.m.service_account.get_json_path(account)
    cmd = [
      self._authutil_path,
      'token',
      '-service-account-json=' + account_file,
      '-json-output', self.m.json.output(),
    ]
    if scopes:
      cmd.extend(['-scopes', ' '.join(scopes)])
    if lifetime_sec is not None:
      cmd.extend(['-lifetime', '%ds' % lifetime_sec])

    return self.m.step(
        'get access token',
        cmd,
        step_test_data=lambda: self.m.json.test_api.output(
            {'token': 'abc123', 'expiry': 123}, name='get access token')
    )
