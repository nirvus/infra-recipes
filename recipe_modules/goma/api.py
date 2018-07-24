# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from recipe_engine import recipe_api


class GomaApi(recipe_api.RecipeApi):
  """GomaApi contains helper functions for using goma."""

  def __init__(self, luci_context, goma_properties, *args, **kwargs):
    super(GomaApi, self).__init__(*args, **kwargs)

    self._luci_context = luci_context
    self._goma_context = None

    self._goma_dir = None
    self._goma_started = False
    self._goma_ctl_env = {}
    self._jobs = goma_properties.get('jobs', None)
    self._recommended_jobs = None
    self._jsonstatus = None

  @property
  def json_path(self):
    assert self._goma_dir
    return self.m.path.join(self._goma_dir, 'jsonstatus')

  @property
  def jsonstatus(self): # pragma: no cover
    return self._jsonstatus

  @property
  def jobs(self):
    """Returns number of jobs for parallel build using Goma.

    Uses value from property "$infra/goma:{\"jobs\": JOBS}" if configured
    (typically in cr-buildbucket.cfg), else defaults to `recommended_goma_jobs`.
    """
    return self._jobs or self.recommended_goma_jobs

  @property
  def recommended_goma_jobs(self):
    """Return the recommended number of jobs for parallel build using Goma.

    Prefer to use just `goma.jobs` and configure it through default builder
    properties in cr-buildbucket.cfg.

    This function caches the _recommended_jobs.
    """
    if self._recommended_jobs is None:
      # When goma is used, 10 * self.m.platform.cpu_count is basically good in
      # various situations according to our measurement. Build speed won't
      # be improved if -j is larger than that.
      #
      # For safety, we'd like to set the upper limit to 200.
      # Note that currently most try-bot build slaves have 8 processors.
      self._recommended_jobs = min(10 * self.m.platform.cpu_count, 200)

    return self._recommended_jobs

  @property
  def goma_ctl(self):
    return self.m.path.join(self._goma_dir, 'goma_ctl.py')

  @property
  def goma_dir(self):
    assert self._goma_dir
    return self._goma_dir

  def ensure_goma(self, canary=False):
    with self.m.step.nest('ensure_goma'):
      with self.m.context(infra_steps=True):
        pkgs = self.m.cipd.EnsureFile()
        ref='release'
        if canary:
          ref='candidate'
        pkgs.add_package('infra_internal/goma/client/${platform}', ref)
        self._goma_dir = self.m.path['cache'].join('goma', 'client')

        self.m.cipd.ensure(self._goma_dir, pkgs)
        return self._goma_dir

  def _run_jsonstatus(self):
    with self.m.context(env=self._goma_ctl_env):
      jsonstatus_result = self.m.python(
          name='goma_jsonstatus', script=self.goma_ctl,
          args=['jsonstatus',
                self.m.json.output(leak_to=self.json_path)],
          step_test_data=lambda: self.m.json.test_api.output(
              data={'notice':[{
                  'infra_status': {
                      'ping_status_code': 200,
                      'num_user_error': 0,
                  }
              }]}))

    self._jsonstatus = jsonstatus_result.json.output
    if self._jsonstatus is None:
      jsonstatus_result.presentation.status = self.m.step.WARNING

  def start(self, env={}, **kwargs):
    """Start goma compiler_proxy.

    A user MUST execute ensure_goma beforehand.
    It is user's responsibility to handle failure of starting compiler_proxy.
    """
    assert self._goma_dir
    assert not self._goma_started

    with self.m.step.nest('pre_goma') as nested_result:
      if 'GOMA_DEPS_CACHE_FILE' not in env:
        self._goma_ctl_env['GOMA_DEPS_CACHE_FILE'] = 'goma_deps_cache'
      if 'GOMA_CACHE_DIR' not in env:
        self._goma_ctl_env['GOMA_CACHE_DIR'] = self.m.path['cache'].join('goma')
      if self._luci_context:
        if not self._goma_context:
          step_result = self.m.json.read(
              'read context', self._luci_context, add_json_log=False,
              step_test_data=lambda: self.m.json.test_api.output({
                'local_auth': {
                  'accounts': [{'id': 'test', 'email': 'some@example.com'}],
                  'default_account_id': 'test',
                }
              })
          )
          ctx = step_result.json.output.copy()
          if 'local_auth' not in ctx: # pragma: no cover
            raise self.m.step.InfraFailure('local_auth missing in LUCI_CONTEXT')
          ctx['local_auth']['default_account_id'] = 'system'
          self._goma_context = self.m.path.mkstemp('luci_context.')
          self.m.file.write_text('write context', self._goma_context,
                                 self.m.json.dumps(ctx))
        self._goma_ctl_env['LUCI_CONTEXT'] = self._goma_context

      # GLOG_log_dir should not be set.
      assert 'GLOG_log_dir' not in self.m.context.env, (
        'GLOG_log_dir must not be set in env during goma.start()')

      goma_ctl_env = self._goma_ctl_env.copy()
      goma_ctl_env.update(env)

      try:
        with self.m.context(env=goma_ctl_env):
          self.m.python(
              name='start_goma',
              script=self.goma_ctl,
              args=['restart'], infra_step=True, **kwargs)
        self._goma_started = True
      except self.m.step.InfraFailure as e: # pragma: no cover
        with self.m.step.defer_results():
          self._run_jsonstatus()

          with self.m.context(env=self._goma_ctl_env):
            self.m.python(
                name='stop_goma (start failure)',
                script=self.goma_ctl,
                args=['stop'], **kwargs)
        nested_result.presentation.status = self.m.step.EXCEPTION
        raise e

  def stop(self, **kwargs):
    """Stop goma compiler_proxy.

    A user MUST execute start beforehand.
    It is user's responsibility to handle failure of stopping compiler_proxy.

    Raises:
        StepFailure if it fails to stop goma.
    """
    assert self._goma_dir
    assert self._goma_started

    with self.m.step.nest('post_goma') as nested_result:
      try:
        with self.m.step.defer_results():
          self._run_jsonstatus()

          with self.m.context(env=self._goma_ctl_env):
            self.m.python(name='goma_stat', script=self.goma_ctl,
                          args=['stat'],
                          **kwargs)
            self.m.python(name='stop_goma', script=self.goma_ctl,
                          args=['stop'], **kwargs)

        self._goma_started = False
      except self.m.step.StepFailure:
        nested_result.presentation.status = self.m.step.EXCEPTION
        raise

  @contextmanager
  def build_with_goma(self, env={}):
    """Make context wrapping goma start/stop.

    Raises:
        StepFailure or InfraFailure if it fails to build.
    """

    self.start(env)
    try:
      yield
    finally:
      self.stop()
