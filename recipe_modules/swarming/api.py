# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
    return (not self._is_error) and ('failure' in self._raw_results['results'])

  def is_infra_failure(self):
    return (self._is_error) or ('internal_failure' in self._raw_results['results'])

  def timed_out(self):
    return (not self._is_error) and self._raw_results['results']['state'] == 'TIMED_OUT'

  def __getitem__(self, key):
    return self._outputs[key]

  @property
  def id(self):
    return self._id

  @property
  def output(self):
    return self._output


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
              idempotent=False, cipd_packages=None, outputs=None):
    """Triggers a Swarming task.

    Args:
      name: name of the task.
      raw_cmd: task command.
      isolated: hash of isolated test on isolate server.
      dump_json: dump details about the triggered task(s).
      dimensions: dimensions to filter slaves on.
      expiration: seconds before this task request expires.
      io_timeout: seconds to allow the task to be silent.
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

  def collect(self, timeout, requests_json=None, tasks=[]):
    """Waits on a set of Swarming tasks.

    Returns both the step result as well as a set of neatly parsed results.

    Args:
      timeout: timeout to wait for result.
      requests_json: load details about the task(s) from the json file.
      tasks: list of task ids to wait on.
    """
    assert self._swarming_client
    assert (requests_json and not tasks) or (not requests_json and tasks)
    outdir = str(self.m.path.mkdtemp("swarming"))
    cmd = [
      self._swarming_client,
      'collect',
      '-server', self.swarming_server,
      '-task-summary-json', self.m.json.output(),
      '-task-output-stdout', 'json',
      '-timeout', timeout,
      '-output-dir', outdir,
    ]
    if requests_json:
      cmd.extend(['-requests-json', requests_json])
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
        step_result.presentation.logs['%s.stdout' % result.id] = result.output.split('\n')

    return parsed_results
