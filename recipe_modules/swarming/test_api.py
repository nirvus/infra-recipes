# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingTestApi(recipe_test_api.RecipeTestApi):

  def trigger(self, name, raw_cmd, task_id='397418be219814a0', dimensions={},
              cipd_packages=[]):
    """Generates step test data intended to mock a swarming API trigger
    method call.

    Args:
      name (str): The name of the triggered task.
      raw_cmd (list[str]): A list of strings representing a CLI command.
      task_id (str): The swarming task ID of the triggered task.
      dimensions (dict[str]str): A dict of dimension names mapping to
        values that were requested as part of this mock swarming task request.
      cipd_packages (list[tuple(str, str, str)]): A structure listing the CIPD
        packages requested to be installed onto this mock swarming task that
        was triggered. The tuple values correspond to the package, path, and
        version of the CIPD package.

    Returns:
      Step test data in the form of JSON output intended to mock a swarming API
      trigger method call.
    """
    return self.m.json.output({
      'TaskID': task_id,
      'ViewURL': 'https://chromium-swarm.appspot.com/user/task/39c188c09955c210',
      'Request': {
        'expiration_secs': '3600',
        'name': name,
        'priority': '100',
        'properties': {
          'cipd_input': {
            'packages': [
              {
                'package_name': pkg,
                'path': path,
                'version': version,
              }  for path, pkg, version in cipd_packages
            ]
          },
          'command': raw_cmd,
          'dimensions': [
            {
              'key': k,
              'value': v,
            } for k, v in sorted(dimensions.iteritems())
          ],
          'execution_timeout_secs': '3600',
          'grace_period_secs': '30',
          'io_timeout_secs': '1200'
        },
        'user': 'luci'
      }
    })

  def _collect_result_data(self):
    return {
      '39927049b6ee7010': {
        'output': 'hello world!',
        'outputs': [],
        'results': {
          'bot_id': 'fuchsia-test-vm',
          'bot_version': 'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c47f2',
          'completed_ts': '2017-11-01T22:06:11.538070',
          'created_ts': '2017-11-01T22:06:08.298510',
          'duration': 0.06629300117492676,
          'exit_code': '2',
          'modified_ts': '2017-11-01T22:06:11.538070',
          'name': 'test',
          'run_id': '39927049b6ee7011',
          'started_ts': '2017-11-01T22:06:09.155530',
          'state': 'COMPLETED',
          'tags': [
            'os:Debian',
            'pool:Fuchsia',
          ],
          'task_id': '39927049b6ee7010',
          'try_number': '1',
          'user': 'luci',
        },
      },
      '39927049b6ae7011': {
        'output': 'hello world!',
        'outputs': ['out/hello.txt'],
        'results': {
          'bot_id': 'fuchsia-test-vm',
          'bot_version': 'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c47f2',
          'completed_ts': '2017-12-01T22:06:11.538070',
          'created_ts': '2017-12-01T22:06:08.298510',
          'duration': 0.06629300117492676,
          'exit_code': '2',
          'failure': True,
          'modified_ts': '2017-12-01T22:06:11.538070',
          'name': 'test',
          'run_id': '39927049b6ae7011',
          'started_ts': '2017-11-01T22:06:09.155530',
          'state': 'COMPLETED',
          'tags': [
            'os:Debian',
            'pool:Fuchsia',
          ],
          'task_id': '39927049b6ae7011',
          'try_number': '1',
          'user': 'luci',
        },
      },
      '39927049b6ae7012': {
        'error': 'something went wrong!',
      },
      '39927049b6ae7013': {
        'output': 'hello world!',
        'outputs': ['out/hello.txt'],
        'results': {
          'bot_id': 'fuchsia-test-vm',
          'bot_version': 'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c47f2',
          'completed_ts': '2017-12-01T22:06:11.538070',
          'created_ts': '2017-12-01T22:06:08.298510',
          'duration': 0.06629300117492676,
          'exit_code': '2',
          'failure': True,
          'modified_ts': '2017-12-01T22:06:11.538070',
          'name': 'test',
          'run_id': '39927049b6ae7011',
          'started_ts': '2017-11-01T22:06:09.155530',
          'state': 'TIMED_OUT',
          'tags': [
            'os:Debian',
            'pool:Fuchsia',
          ],
          'task_id': '39927049b6ae7013',
          'try_number': '1',
          'user': 'luci',
        },
      },
    }

  def collect(self, task_ids=(), task_failure=False, infra_failure=False,
              timed_out=False, output=None, outputs=()):
    """Generates test step data for the swarming API collect method.

    Args:
      task_ids (seq[str]): A sequence of task IDs, which will be assigned to
        the collect results that are returned. The length of this sequence
        also determines the amount of collect results to return.
      task_failure (bool): Whether or not all of the results should be task
        failures.
      infra_failure (bool): Whether or not all of the results should be infra
        failures.
      timed_out (bool): Whether or not all of the results should have timed out.
      output (str): Mock output for the swarming task.
      outputs (seq[str]): A sequence of mock outputs (relative paths) to attach
        to each collect result.

    Returns:
      Step test data in the form of JSON output intended to mock a swarming API
      collect method call. If task_ids is left unspecified, it returns a single
      collect result with a sample task ID.
    """
    if task_failure:
      id = '39927049b6ae7011'
    elif infra_failure:
      id = '39927049b6ae7012'
    elif timed_out:
      id = '39927049b6ae7013'
    else:
      id = '39927049b6ee7010'
    data = self._collect_result_data()[id]
    if output:
      data['output'] = output
    if outputs:
      data['outputs'] = outputs
    if not task_ids:
      task_ids = [id]
    return self.m.json.output({id: data for id in task_ids})
