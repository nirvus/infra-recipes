# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

class TiloApi(recipe_api.RecipeApi):
  InvocationPassed = 'succeeded'
  InvocationFailed = 'failed'

  def __init__(self, tilo_properties, *args, **kwargs):
    super(TiloApi, self).__init__(*args, **kwargs)
    self._credentials = tilo_properties.get('credentials')
    self._executable = tilo_properties.get('executable')
    self._project_id = tilo_properties.get('project-id')
    self._db_path = None

  def __call__(self, *args):
    assert self._executable

    new_env = self.m.context.env
    new_env.setdefault('GOOGLE_APPLICATION_CREDENTIALS', self._credentials)

    with self.m.context(env=new_env):
      full_cmd = [self._executable]
      full_cmd.extend(args)
      return self.m.step('run tilo', full_cmd)

  def set_database_path(self, db_path):
    self._db_path = db_path

  def init(self):
    #yapf: disable
    return self(
      'init',
      '-staging',
      '-project', self._project_id,
      '-database', self.m.json.output(leak_to=self._db_path),
    )
    #yapf: enable

  def process_summary(self, summary):
    #yapf: disable
    return self(
      'process-summary',
      '-database', self._db_path,
      '-summary', summary,
    )
    #yapf: enable

  def invocation_start(self):
    #yapf: disable
    return self(
      'invocation-start',
      '-database', self._db_path,
    )
    #yapf: enable

  def environment_found(self, name):
    #yapf: disable
    return self(
      'environment-found',
      '-database', self._db_path,
      '-name', name,
    )
    #yapf: enable

  def target_found(self, name, environments):
    #yapf: disable
    return self(
      'target-found',
      '-database', self._db_path,
      '-name', name,
    )
    #yapf: enable

  def test_started(self, target, environment, test_suite):
    #yapf: disable
    return self(
      'test-started',
      '-database', self._db_path,
      '-target', target,
      '-environment', environment,
      '-test-suite', test_suite,
    )
    #yapf: enable

  def test_finished(self, target, environment, test_suite, result):
    #yapf: disable
    return self(
      'test-finished',
      '-database', self._db_path,
      '-target', target,
      '-environment', environment,
      '-test-suite', test_suite,
      '-result', result,
    )
    #yapf: enable

  def invocation_end(self, result):
    #yapf: disable
    return self(
      'invocation-end',
      '-database', self._db_path,
      '-result', result,
    )
    #yapf: enable
