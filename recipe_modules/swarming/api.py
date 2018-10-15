# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
from recipe_engine import recipe_api


class CollectResult(object):
  """Wrapper object for collect results."""

  def __init__(self, m, id, raw_results, outdir):
    self._id = id
    self._raw_results = raw_results
    self._is_error = 'error' in raw_results
    self._outputs = {}
    if self._is_error:
      self._output = self._raw_results['error']
    else:
      self._output = self._raw_results['output']
      if self._raw_results.get('outputs'):
        self._outputs = {
            output: m.path.join(outdir, id, output)
            for output in self._raw_results['outputs']
        }

  def is_failure(self):
    return ((not self._is_error) and
            ('failure' in self._raw_results['results']))

  def is_infra_failure(self):
    return ((self._is_error) or
            ('internal_failure' in self._raw_results['results']))

  def timed_out(self):
    return ((not self._is_error) and
            self._raw_results['results']['state'] == 'TIMED_OUT')

  def expired(self):
    return ((not self._is_error) and
            self._raw_results['results']['state'] == 'EXPIRED')

  def no_resource(self):
    return ((not self._is_error) and
            self._raw_results['results']['state'] == 'NO_RESOURCE')

  # TODO(mknyszek): Remove this in favor of using outputs directly.
  def __getitem__(self, key):
    return self._outputs[key]

  @property
  def name(self):
    return self._raw_results['results']['name'] if not self._is_error else None

  @property
  def id(self):
    return self._id

  @property
  def output(self):
    return self._output

  @property
  def outputs(self):
    return self._outputs


class TaskRequest(object):
  """Wrapper object for constructing a Swarming task request."""

  def __init__(self, name, cmd, dimensions, isolated='', isolate_server='',
               expiration_secs=300, io_timeout_secs=60, hard_timeout_secs=1200,
               idempotent=False, secret_bytes='', cipd_packages=(), outputs=()):
    """Creates a Swarming task request object.

    For more details on what goes into a Swarming task, see the user guide:
    https://github.com/luci/luci-py/blob/master/appengine/swarming/doc/User-Guide.md#task

    Args:
      name (str): Name of the task.
      cmd (list[str]): The command that will be executed by the swarming_bot in
        the task.
      isolated (str): Hash of isolated on isolate server.
      isolate_server (str): Base URL of the isolate server.
      dimensions (dict[str]str): Dimensions to filter swarming bots on.
      expiration_secs (int): Seconds before this task request expires.
      io_timeout_secs (int): Seconds to allow the task to be silent.
      hard_timeout_secs (int): Seconds before swarming should kill the task.
      idempotent (bool): Whether this task is considered idempotent. Idempotent
        tasks are such that if another task is executed with identical
        properties, we can short-circuit execution and just return the other
        task's results.
      secret_bytes (str): Data that can securely be passed to the task.
      cipd_packages (list[(str,str,str)]: List of 3-tuples corresponding to
        CIPD packages needed for the task: ('path', 'package_name', 'version'),
        defined as follows:
          path: Path relative to the Swarming root dir in which to install
            the package.
          package_name: Name of the package to install,
            eg. "infra/tools/authutil/${platform}"
          version: Version of the package, either a package instance ID,
            ref, or tag key/value pair.
      outputs (list[str]): List of paths to files which can be downloaded via
        collect().
    """
    assert len(dimensions) >= 1 and dimensions['pool']
    self.name = name
    self.cmd = cmd
    self.isolate_server = isolate_server
    self.isolated = isolated
    self.dimensions = dimensions
    self.expiration_secs = expiration_secs
    self.io_timeout_secs = io_timeout_secs
    self.hard_timeout_secs = hard_timeout_secs
    self.idempotent = idempotent
    self.secret_bytes = base64.b64encode(secret_bytes)
    self.cipd_packages = cipd_packages
    self.outputs = outputs

  def render_to_json(self):
    """Renders the task request as a JSON-serializable dict.

    The format follows the Swarming task request API, which may be found here:
    https://chromium.googlesource.com/infra/luci/luci-go/+/819bad947699d6a3168d476281528b73abfe32d0/common/api/swarming/swarming/v1/swarming-api.json#1313
    """
    properties = {
      'command': self.cmd,
      'dimensions': [
        {
          'key': k,
          'value': v,
        }
        for k, v in self.dimensions.iteritems()
      ],
      'execution_timeout_secs': str(self.hard_timeout_secs),
      'io_timeout_secs': str(self.io_timeout_secs),
      # When a Swarming task is killed, the grace period is the amount of time
      # to wait before a SIGKILL is issued to the process, allowing it to
      # perform any clean-up operations.
      'grace_period_secs': str(30),
      'idempotent': self.idempotent,
      'outputs': self.outputs,
    }
    if self.isolate_server and self.isolated:
      properties['inputs_ref'] = {
        'isolated': self.isolated,
        'namespace': 'default-gzip',
        'isolatedserver': self.isolate_server,
      }
    if self.secret_bytes:
      properties['secret_bytes'] = self.secret_bytes
    if self.cipd_packages:
      properties['cipd_input'] = {
        'packages': [
          {
            'package_name': name,
            'path': path,
            'version': version,
          }
          for path, name, version in self.cipd_packages
        ],
      }
    return {
      'name': self.name,
      'expiration_secs': str(self.expiration_secs),
      # Priority is a numerical priority between 0 and 255 where a higher
      # number corresponds to a lower priority. Tasks are scheduled by swarming
      # in order of their priority (e.g. if both a task of priority 1 and a task
      # of priority 2 are waiting for resources to free up for execution, the
      # task with priority 1 will take precedence).
      'priority': str(200),
      'properties': properties,
    }


class SwarmingApi(recipe_api.RecipeApi):
  """APIs for interacting with swarming."""

  def __init__(self, swarming_server, *args, **kwargs):
    super(SwarmingApi, self).__init__(*args, **kwargs)
    self._swarming_server = swarming_server
    self._swarming_client = None

  def __call__(self, *args, **kwargs):
    """Return a swarming command step."""
    assert self._swarming_client
    name = kwargs.pop('name', 'swarming ' + args[0])
    return self.m.step(name, [self._swarming_client] + list(args), **kwargs)

  def ensure_swarming(self, version=None):
    """Ensures that swarming client is installed."""
    if self._swarming_client:
      return self._swarming_client

    with self.m.step.nest('ensure_swarming'):
      with self.m.context(infra_steps=True):
        swarming_package = ('infra/tools/luci/swarming/%s' %
            self.m.cipd.platform_suffix())
        luci_dir = self.m.path['start_dir'].join('cipd', 'luci', 'swarming')

        self.m.cipd.ensure(luci_dir,
                           {swarming_package: version or 'release'})
        self._swarming_client = luci_dir.join('swarming')

        return self._swarming_client

  @property
  def swarming_client(self):
    return self._swarming_client

  @property
  def swarming_server(self):
    """URL of Swarming server to use, default is a production one."""
    return self._swarming_server

  @swarming_server.setter
  def swarming_server(self, value):
    """Changes URL of Swarming server to use."""
    self._swarming_server = value

  def trigger(self, name, raw_cmd, isolated=None, dump_json=None,
              dimensions=None, expiration=None, io_timeout=None,
              hard_timeout=None, idempotent=False, cipd_packages=None,
              outputs=None):
    """Triggers a Swarming task.

    Args:
      name: name of the task.
      raw_cmd: task command.
      isolated: hash of isolated test on isolate server.
      dump_json: dump details about the triggered task(s).
      dimensions: dimensions to filter slaves on.
      expiration: seconds before this task request expires.
      io_timeout: seconds to allow the task to be silent.
      hard_timeout: seconds before swarming should kill the task.
      idempotent: whether this task is considered idempotent.
      cipd_packages: list of 3-tuples corresponding to CIPD packages needed for
          the task: ('path', 'package_name', 'version'), defined as follows:
              path: Path relative to the Swarming root dir in which to install
                  the package.
              package_name: Name of the package to install,
                  eg. "infra/tools/authutil/${platform}"
              version: Version of the package, either a package instance ID,
                  ref, or tag key/value pair.
      outputs: list of paths to files which can be downloaded via collect.
    """
    assert self._swarming_client
    cmd = [
      self._swarming_client,
      'trigger',
      '-isolate-server', self.m.isolated.isolate_server,
      '-server', self.swarming_server,
      '-task-name', name,
      '-namespace', 'default-gzip',
      '-dump-json', self.m.json.output(leak_to=dump_json),
    ]
    if isolated:
      cmd.extend(['-isolated', isolated])
    if dimensions:
      for k, v in sorted(dimensions.iteritems()):
        cmd.extend(['-dimension', '%s=%s' % (k, v)])
    if expiration:
      cmd.extend(['-expiration', str(expiration)])
    if io_timeout:
      cmd.extend(['-io-timeout', str(io_timeout)])
    if hard_timeout:
      cmd.extend(['-hard-timeout', str(hard_timeout)])
    if idempotent:
      cmd.append('-idempotent')
    if cipd_packages:
      for path, pkg, version in cipd_packages:
        cmd.extend(['-cipd-package', '%s:%s=%s' % (path, pkg, version)])
    if outputs:
      for output in outputs:
        cmd.extend(['-output', output])
    cmd.extend(['-raw-cmd', '--'] + raw_cmd)
    return self.m.step(
        'trigger %s' % name,
        cmd,
        step_test_data=lambda: self.test_api.trigger(name, raw_cmd,
            dimensions=dimensions, cipd_packages=cipd_packages)
    )

  def task_request(self, *args, **kwargs):
    """Creates a new TaskRequest object.

    Passes down all arguments to the TaskRequest constructor with the exception
    of isolate_server, which is provided by the isolated recipe module.
    """
    return TaskRequest(*args, **dict(
        kwargs, isolate_server=self.m.isolated.isolate_server))

  def spawn_tasks(self, tasks=(), json_output=None):
    """Spawns a set of Swarming tasks.

    Args:
      tasks (seq[TaskRequest]): A sequence of task request objects representing
        the tasks we want to spawn.
      json_output (Path): Optional filepath to leak a JSON file containing
        the return value of this method.

    Returns:
      A Python dict representing the JSON spawn response that may be passed into
        collect().
    """
    assert len(tasks) > 0

    requests = []
    for task in tasks:
      requests.append(task.render_to_json())

    spawn_resp = self.m.step(
        'spawn %d tasks' % len(tasks),
        [
          self._swarming_client,
          'spawn-tasks',
          '-server', self.swarming_server,
          '-json-input', self.m.json.input({'requests': requests}),
          '-json-output', self.m.json.output(leak_to=json_output),
        ],
        step_test_data=lambda: self.test_api.spawn_tasks(tasks),
    ).json.output

    presented_links = self.m.step.active_result.presentation.links
    for task in spawn_resp['tasks']:
      task_id = task['task_id']
      name = task['request']['name']
      presented_links['Swarming task: %s' % name] = (
          '%s/task?id=%s' % (self.swarming_server, task_id)
      )

    return spawn_resp

  def collect(self, timeout=None, tasks_json=None, tasks=[]):
    """Waits on a set of Swarming tasks.

    Returns both the step result as well as a set of neatly parsed results.

    Args:
      timeout: timeout to wait for result.
      tasks_json: load details about the task(s) from the json file.
      tasks: list of task ids to wait on.
    """
    assert self._swarming_client
    assert (tasks_json and not tasks) or (not tasks_json and tasks)
    outdir = str(self.m.path.mkdtemp("swarming"))
    cmd = [
      self._swarming_client,
      'collect',
      '-server', self.swarming_server,
      '-task-summary-json', self.m.json.output(),
      '-task-output-stdout', 'json',
      '-output-dir', outdir,
    ]
    if timeout:
      cmd.extend(['-timeout', timeout])
    if tasks_json:
      cmd.extend(['-requests-json', tasks_json])
    if tasks:
      cmd.extend(tasks)
    cmd.extend([])
    step_result = self.m.step(
        'collect',
        cmd,
        infra_step=True,
        step_test_data=lambda: self.test_api.collect()
    )
    parsed_results = [
        CollectResult(self.m, id, task, outdir)
        for id, task in step_result.json.output.iteritems()
    ]

    # Fix presentation on collect to reflect bot results.
    for result in parsed_results:
      if result.output:
        step_result.presentation.logs['Swarming task output: %s' % result.name] = (
          result.output.split('\n')
        )

    return parsed_results
