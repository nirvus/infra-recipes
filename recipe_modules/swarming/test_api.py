# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingTestApi(recipe_test_api.RecipeTestApi):

  def trigger(self, name, raw_cmd, dimensions=[], cipd_packages=[]):
    return self.m.json.output({
      'base_task_name': name,
      'tasks': [
        {
          'shard_index': 0,
          'task_id': '398db31cc90be910',
          'view_url': 'https://chromium-swarm.appspot.com/user/task/398db31cc90be910'
        }
      ],
      'request': {
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
        'user': 'luci',
      }
    })

  def collect(self):
    return self.m.json.output({
      'shards': [{
        'results': {
          'bot_id': 'fuchsia-test-vm',
          'bot_version': 'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c47f2',
        },
        'completed_ts': '2017-11-01T22:06:11.538070',
        'created_ts': '2017-11-01T22:06:08.298510',
        'duration': 0.06629300117492676,
        'exit_code': '2',
        'failure': True,
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
        'user': 'luci'
      }]
    })
