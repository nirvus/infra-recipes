# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class FuchsiaTestApi(recipe_test_api.RecipeTestApi):

  def task_step_data(self,
                     output='',
                     device=False,
                     task_failure=False,
                     infra_failure=False,
                     timed_out=False):
    """Returns mock step data for task results.

    This should be used by any test which calls api.fuchsia.test*().

    Args:
      output (str): The mock task's stdout/stderr.
      device (bool): Whether we're mocking testing on a hardware device.
      task_failure (bool): Whether the task failed.
      infra_failure (bool): Whether there was an infra failure in executing the
        task.
      timed_out (bool): Whether the task timed out.

    Returns:
      RecipeTestApi.step_data for the collect step.
    """
    return self.step_data('collect',
                          self.m.swarming.collect(
                              output=output,
                              outputs=['out.tar'] if device else ['output.fs'],
                              task_failure=task_failure,
                              infra_failure=infra_failure,
                              timed_out=timed_out,))

  def test_step_data(self, failure=False):
    """Returns mock step data for test results.

    This should be used by any test which calls api.fuchsia.test*() and expects
    it to make it to the tests analysis phase.

    Args:
      failure (bool): Whether a test failed or not.

    Returns:
      RecipeTestApi.step_data for the extract_results step.
    """
    result = 'FAIL' if failure else 'PASS'
    return self.step_data(
        'extract results',
        self.m.raw_io.output_dir({
            'summary.json':
                '{"tests":[{"name": "/hello", "output_file": "hello.out", "result": "%s"}]}'
                % result,
            'hello.out':
                'hello',
        }))
