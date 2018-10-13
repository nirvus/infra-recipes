# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingTestApi(recipe_test_api.RecipeTestApi):

  def trigger(self,
              name,
              raw_cmd,
              task_id='397418be219814a0',
              dimensions={},
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
      Step test data in the form of JSON response output intended to mock a
      swarming API trigger method call.
    """
    # TODO(mknyszek): Create instructions for updating this if the output format
    # changes.
    return self.m.json.output({
        'tasks': [{
            'task_id': task_id,
            'request': {
                'expiration_secs': '3600',
                'name': name,
                'priority': '100',
                'properties': {
                    'cipd_input': {
                        'packages': [{
                            'package_name': pkg,
                            'path': path,
                            'version': version,
                        } for path, pkg, version in cipd_packages]
                    },
                    'command':
                        raw_cmd,
                    'dimensions': [{
                        'key': k,
                        'value': v,
                    } for k, v in sorted(dimensions.iteritems())],
                    'execution_timeout_secs':
                        '3600',
                    'grace_period_secs':
                        '30',
                    'io_timeout_secs':
                        '1200'
                },
                'user': 'luci'
            },
        },],
    })

  def spawn_tasks(self, tasks):
    """Generates step test data intended to mock a swarming API spawn_tasks
    method call.

    Args:
      tasks (seq[api.swarming.TaskRequest]): A sequence of task request objects
        representing the tasks we want to spawn.

    Returns:
      Step test data in the form of JSON response output intended to mock a
      swarming API spawn_tasks method call.
    """
    return self.m.json.output({
        'tasks': [{
            'task_id': '39927049b6ee701%d' % ind,
            'request': {
                'expiration_secs': '3600',
                'name': task.name,
                'priority': '100',
                'properties': {
                    'cipd_input': {
                        'packages': [{
                            'package_name': pkg,
                            'path': path,
                            'version': version,
                        } for path, pkg, version in task.cipd_packages]
                    },
                    'command':
                        task.cmd,
                    'dimensions': [{
                        'key': k,
                        'value': v,
                    } for k, v in sorted(task.dimensions.iteritems())],
                    'execution_timeout_secs':
                        '3600',
                    'grace_period_secs':
                        '30',
                    'io_timeout_secs':
                        '1200'
                },
                'user': 'luci'
            },
        } for ind, task in enumerate(tasks)],
    })

  @staticmethod
  def task_success(id='39927049b6ee7010',
                   name='test',
                   output=None,
                   outputs=()):
    output = output or 'hello world!'
    # TODO(mknyszek): Create a helper to avoid copy-pasting this entire dict.
    return {
        'output': output,
        'outputs': outputs,
        'results': {
            'bot_id':
                'fuchsia-test-vm',
            'bot_version': (
                'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c'
                '47f2'),
            'completed_ts':
                '2017-11-01T22:06:11.538070',
            'created_ts':
                '2017-11-01T22:06:08.298510',
            'duration':
                0.06629300117492676,
            'exit_code':
                '0',
            'modified_ts':
                '2017-11-01T22:06:11.538070',
            'name':
                name,
            'run_id':
                '39927049b6ee7011',
            'started_ts':
                '2017-11-01T22:06:09.155530',
            'state':
                'COMPLETED',
            'tags': [
                'os:Debian',
                'pool:Fuchsia',
            ],
            'task_id':
                id,
            'try_number':
                '1',
            'user':
                'luci',
        },
    }

  @staticmethod
  def task_failure(id='39927049b6ae7011',
                   name='test',
                   output=None,
                   outputs=None):
    output = output or 'hello world!'
    outputs = outputs or ['out/hello.txt']
    # TODO(mknyszek): Create a helper to avoid copy-pasting this entire dict.
    return {
        'output': output,
        'outputs': outputs,
        'results': {
            'bot_id':
                'fuchsia-test-vm',
            'bot_version': (
                'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c'
                '47f2'),
            'completed_ts':
                '2017-11-01T22:06:11.538070',
            'created_ts':
                '2017-11-01T22:06:08.298510',
            'duration':
                0.06629300117492676,
            'exit_code':
                '1',
            'failure':
                True,
            'modified_ts':
                '2017-11-01T22:06:11.538070',
            'name':
                name,
            'run_id':
                '39927049b6ee7011',
            'started_ts':
                '2017-11-01T22:06:09.155530',
            'state':
                'COMPLETED',
            'tags': [
                'os:Debian',
                'pool:Fuchsia',
            ],
            'task_id':
                id,
            'try_number':
                '1',
            'user':
                'luci',
        },
    }

  @staticmethod
  def task_infra_failure(id='39927049b6ae7012', outputs=None):
    task_datum = {'error': 'something went wrong!', 'results': {'task_id': id,}}
    if outputs:
      task_datum['outputs'] = outputs
    return task_datum

  @staticmethod
  def task_timed_out(id='39927049b6ae7013',
                     name='test',
                     output=None,
                     outputs=None):
    output = output or 'hello world!'
    outputs = outputs or ['out/hello.txt']
    # TODO(mknyszek): Create a helper to avoid copy-pasting this entire dict.
    return {
        'output': output,
        'outputs': outputs,
        'results': {
            'bot_id':
                'fuchsia-test-vm',
            'bot_version': (
                'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c'
                '47f2'),
            'completed_ts':
                '2017-11-01T22:06:11.538070',
            'created_ts':
                '2017-11-01T22:06:08.298510',
            'duration':
                0.06629300117492676,
            'failure':
                True,
            'modified_ts':
                '2017-11-01T22:06:11.538070',
            'name':
                name,
            'run_id':
                '39927049b6ee7011',
            'started_ts':
                '2017-11-01T22:06:09.155530',
            'state':
                'TIMED_OUT',
            'tags': [
                'os:Debian',
                'pool:Fuchsia',
            ],
            'task_id':
                id,
            'try_number':
                '1',
            'user':
                'luci',
        },
    }

  @staticmethod
  def task_expired(id='39927049b6ae7013', name='test'):
    # TODO(mknyszek): Create a helper to avoid copy-pasting this entire dict.
    return {
        'output': '',
        'outputs': None,
        'results': {
            'bot_id':
                'fuchsia-test-vm',
            'bot_version': (
                'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c'
                '47f2'),
            'completed_ts':
                '2017-11-01T22:06:11.538070',
            'created_ts':
                '2017-11-01T22:06:08.298510',
            'duration':
                0.06629300117492676,
            'modified_ts':
                '2017-11-01T22:06:11.538070',
            'name':
                name,
            'run_id':
                '39927049b6ee7011',
            'started_ts':
                '2017-11-01T22:06:09.155530',
            'state':
                'EXPIRED',
            'tags': [
                'os:Debian',
                'pool:Fuchsia',
            ],
            'task_id':
                id,
            'try_number':
                '1',
            'user':
                'luci',
        },
    }

  @staticmethod
  def task_no_resource(id='39927049b6ae7013', name='test'):
    # TODO(mknyszek): Create a helper to avoid copy-pasting this entire dict.
    return {
        'output': '',
        'outputs': None,
        'results': {
            'bot_id':
                'fuchsia-test-vm',
            'bot_version': (
                'f5f38a01bce09e3491fbd51c5974a03707915d0d7ebd5f9ee0186051895c'
                '47f2'),
            'completed_ts':
                '2017-11-01T22:06:11.538070',
            'created_ts':
                '2017-11-01T22:06:08.298510',
            'duration':
                0.06629300117492676,
            'modified_ts':
                '2017-11-01T22:06:11.538070',
            'name':
                name,
            'run_id':
                '39927049b6ee7011',
            'started_ts':
                '2017-11-01T22:06:09.155530',
            'state':
                'NO_RESOURCE',
            'tags': [
                'os:Debian',
                'pool:Fuchsia',
            ],
            'task_id':
                id,
            'try_number':
                '1',
            'user':
                'luci',
        },
    }

  def collect(self, task_data=None):
    """Generates test step data for the swarming API collect method.

    Args:
      task_data (seq[dict]): A sequence of dicts based on the return value of
        task_success(), task_failure(), task_infra_failure(), or
        task_timed_out(). Must be a super-set of {'results': {'task_id': <str>}}

    Returns:
      Step test data in the form of JSON output intended to mock a swarming API
      collect method call. If task_data is left unspecified, it returns a single
      collect result with an arbitrary task ID.
    """
    task_data = task_data or [self.task_success()]
    id_to_data = {datum['results']['task_id']: datum for datum in task_data}
    return self.m.json.output(id_to_data)
