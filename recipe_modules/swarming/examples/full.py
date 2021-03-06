# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property


DEPS = [
  'swarming',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/properties',
]


PROPERTIES = {
  'spawn_tasks':
      Property(
          kind=bool,
          help='Whether to use spawn_tasks or trigger',
          default=True),
}


def RunSteps(api, spawn_tasks):
  api.swarming.ensure_swarming()

  # Ensuring again should have no effect
  api.swarming.ensure_swarming()

  assert api.swarming.swarming_client

  api.swarming.swarming_server = 'chromium-swarm-dev.appspot.com'

  json = api.path['cleanup'].join('task.json')

  if spawn_tasks:
    # Create a new Swarming task request.
    request = api.swarming.task_request(
        name='recipes-go',
        cmd=['recipes', 'run', '"example"'],
        dimensions={'pool': 'Fuchsia', 'os': 'Debian'},
        isolated='606d94add94223636ee516c6bc9918f937823ccc',
        expiration_secs=3600,
        io_timeout_secs=600,
        hard_timeout_secs=3600,
        idempotent=True,
        secret_bytes='shh, don\'t tell',
        outputs=['out/hello.txt'],
        cipd_packages=[('cipd_bin_packages', 'infra/git/${platform}', 'version:2.14.1.chromium10')],
    )

    # Spawn the task request. This is equivalent to trigger.
    api.swarming.spawn_tasks(
        tasks=[request],
        json_output=json,
    )
  else:
    # Trigger a new Swarming task.
    api.swarming.trigger('recipes-go',
        ['recipes', 'run', '"example"'],
        isolated='606d94add94223636ee516c6bc9918f937823ccc',
        dump_json=json,
        dimensions={'pool': 'Fuchsia', 'os': 'Debian'},
        expiration=3600,
        io_timeout=600,
        hard_timeout=3600,
        idempotent=True,
        outputs=['out/hello.txt'],
        cipd_packages=[('cipd_bin_packages', 'infra/git/${platform}', 'version:2.14.1.chromium10')],
    )

  # Wait for its results.
  try:
    results = api.swarming.collect(timeout='1m', tasks_json=json)

    if results[0].state == api.swarming.TaskState.RPC_FAILURE:
      # name should be None.
      assert results[0].name is None
      raise api.step.InfraFailure('Failed to collect: %s' % results[0].output)
    elif results[0].state == api.swarming.TaskState.TIMED_OUT:
      raise api.step.StepTimeout('Timed out during execution', '180 seconds')
    elif results[0].state == api.swarming.TaskState.NO_RESOURCE:
      raise api.step.InfraFailure('Found no bots to run this task')
    elif results[0].state == api.swarming.TaskState.EXPIRED:
      raise api.step.InfraFailure('Timed out waiting for a bot to run on')
    elif results[0].state == api.swarming.TaskState.BOT_DIED:
      raise api.step.InfraFailure('The bot running this task died')
    elif results[0].state == api.swarming.TaskState.CANCELED:
      raise api.step.InfraFailure('The task was canceled before it could run')
    elif results[0].state == api.swarming.TaskState.KILLED:
      raise api.step.InfraFailure('The task was killed mid-execution')

    # You can grab the task's name.
    results[0].name
    # You can grab the task's ID.
    results[0].id
    # You can grab the task's output.
    results[0].output
    # You can also grab the outputs of the Swarming task as a map.
    results[0].outputs
  except:
    pass

  # You can also wait on arbitrary tasks.
  api.swarming.collect(tasks=['398db31cc90be910', 'a9123129aaaaaa'], timeout='30m')

  # You can also run an arbitrary command.
  api.swarming('version')


def GenTests(api):
  yield api.test('success') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.SUCCESS,
                               output='hello',
                               outputs=['out/hello.txt'])]))
  yield api.test('task_failure') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.TASK_FAILURE)]))
  yield api.test('rpc_failure') + api.step_data(
      'collect', api.swarming.collect(task_data=[
          api.swarming.task_data(state=api.swarming.TaskState.RPC_FAILURE)]))
  yield api.test('task_timeout') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.TIMED_OUT)]))
  yield api.test('task_expired') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.EXPIRED)]))
  yield api.test('no_resource') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.NO_RESOURCE)]))
  yield api.test('bot_died') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.BOT_DIED)]))
  yield api.test('task_canceled') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.CANCELED)]))
  yield api.test('task_killed') + api.step_data(
      'collect', api.swarming.collect(task_data=[
        api.swarming.task_data(state=api.swarming.TaskState.KILLED)]))
  yield api.test('infra_failure_no_out') + api.step_data(
      'collect', api.json.output({}))
  yield api.test('basic_trigger') + api.step_data(
      'collect', api.swarming.collect(task_data=[api.swarming.task_data(
          output='hello', outputs=['out/hello.txt'])])) + api.properties(
              spawn_tasks=False)
