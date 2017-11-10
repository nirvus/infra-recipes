# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingTestApi(recipe_test_api.RecipeTestApi):

  def trigger(self, name, raw_cmd, dimensions=[], cipd_packages=[]):
    return self.m.json.output({
      'TaskID': '397418be219814a0',
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
    return [{
      'output': 'hello world!',
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
    {
      'output': 'hello world!',
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
        'task_id': '39927049b6ae7010',
        'try_number': '1',
        'user': 'luci',
      },
    },
    {
      'code': 400,
      'message': '39casdgasd8c09955c210 is an invalid key.',
      'Body': '{"error": {"message": "39casdgasd8c09955c210 is an invalid key."}}',
      'Header': None,
      'Errors': None,
    }]

  def collect_result(self, task_failure=False, infra_failure=False):
    if task_failure:
      data = self._collect_result_data()[1]
    elif infra_failure:
      data = self._collect_result_data()[2]
    else:
      data = self._collect_result_data()[0]
    return self.m.json.output({'tasks': [data]})

  def collect(self):
    return self.m.json.output({'tasks': self._collect_result_data()})
