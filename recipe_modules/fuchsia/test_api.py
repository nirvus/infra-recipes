# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class FuchsiaTestApi(recipe_test_api.RecipeTestApi):

  def test(self,
           name,
           clear_default_properties=False,
           clear_default_steps=False,
           tryjob=False,
           expect_failure=False,
           build_metrics_gcs_bucket=None,
           test_coverage_gcs_bucket=None,
           properties=None,
           steps=()):  # pragma: no cover
    """Returns a test case appropriate for yielding from GenTests().

    Provides default property values for the common cases.

    Args:
      name: Test name.
      clear_default_properties: If true, does not provide default values.
          However, setting tryjob=True does still add the tryjob-related
          properties. Buildbucket properties are always added.
      clear_default_steps: If true, does not automatically add steps
          based on the input properties.
      tryjob: If true, adds tryjob-related properties.
      expect_failure: If true, the test is expected to fail before
          completion, so certain common steps shouldn't be expected to happen.
      properties: A required dict of properties to override for this test.
      steps: An optional sequence of RecipeTestApi.step_data objects to append to
          the output of this function.

    Returns:
      TestData object.
    """
    # Tests shouldn't try to create their own tryjob environment, in the same way
    # that cr-buildbucket builders shouldn't specify tryjob-related properties.
    if 'tryjob' in properties:
      # TODO(dbort): Maybe check for patch_ properties, too.
      raise ValueError('Test "%s": Do not specify a "tryjob" property; '
                       'use the tryjob arg.' % name)  # pragma: no cover

    if clear_default_properties:
      final_properties = {}
    else:
      final_properties = dict(
          manifest='fuchsia',
          remote='https://fuchsia.googlesource.com/manifest',
          project='topaz',
          target='x64',
          packages=['topaz/packages/default'],
          revision=self.m.jiri.example_revision,
      )

    if 'buildbucket' in properties:
      # Re-evaluate this restriction if a test really needs to specify its
      # own buildbucket properties.
      raise ValueError(
          'Test "%s": Do not specify a "buildbucket" property; '
          'the test API should provide it.' % name)  # pragma: no cover
    # Used by api.buildbucket.
    final_properties['buildbucket'] = {
        'build': {
            'bucket': '###buildbucket-bucket###',
            'id': '5555555555',
            'project': '###buildbucket-project###',
            'tags': ['builder:###buildbucket-builder###'],
        },
    }

    if tryjob:
      gerrit_project = (
          properties.get('project', None) or
          final_properties.get('project', 'topaz'))
      final_properties.update(
          dict(
              # properties.tryserver will add patch_* properties based on
              # these gerrit_* properties.
              gerrit_url='https://fuchsia-review.googlesource.com',
              gerrit_project=gerrit_project,
              tryjob=True,
          ))

    if build_metrics_gcs_bucket:
      final_properties['$infra/fuchsia'] = {
          'build_metrics_gcs_bucket': build_metrics_gcs_bucket,
      }

    if test_coverage_gcs_bucket:
      final_properties['$infra/fuchsia'] = {
          'test_coverage_gcs_bucket': test_coverage_gcs_bucket,
      }

    # Provided properties override the defaults.
    final_properties.update(properties)

    # Add implicit steps.
    extra_steps = []
    if not clear_default_steps:
      # Don't add these if the test is expected to raise an exception;
      # the recipes engine will complain that these steps aren't consumed.
      run_tests = final_properties.get('run_tests', False)
      run_host_tests = final_properties.get('run_host_tests', False)
      on_device = final_properties.get('device_type', 'QEMU') != 'QEMU'
      requires_secrets = final_properties.get('requires_secrets', False)

      if requires_secrets:
        extra_steps.extend(self.secrets_step_data())
      if run_tests:
        extra_steps.append(self.images_step_data())
        if not expect_failure:
          extra_steps.append(self.task_step_data(device=on_device))
          extra_steps.append(self.test_step_data())
      if run_host_tests and not expect_failure:
        extra_steps.append(self.test_step_data(host_results=True))

    # Assemble the return value.
    ret = super(FuchsiaTestApi, self).test(name)

    if tryjob:
      ret += self.m.properties.tryserver(**final_properties)
    else:
      ret += self.m.properties(**final_properties)

    for s in extra_steps:
      ret += s
    for s in steps:
      # Provided steps override implicit steps.
      ret += s
    return ret

  def breakpad_symbol_summary(self, summary_json):
    """Returns mock data for the summary file written by //tools/dump_breakpad_symbols.

    Args:
      summary_json (Dict): The contents of the dump_breakpad_symbols summary file.
        The summary is a JSON object whose keys are absolute paths to binaries and
        values are absolute paths to the generated breakpad symbol files for those
        those binaries. See //tools/cmd/dump_breakpad_symbols for more information.

    Returns:
      RecipeTestApi.step_data for the 'read symbol file summary' step.
    """
    return self.step_data('read symbol file summary',
                          self.m.json.output(summary_json))

  def images_step_data(self, has_data_template=True):
    """Returns mock step data for the image manifest."""
    mock_image_manifest = [
          {'name': 'zircon-a',
          'type': 'zbi',
          'path': 'fuchsia.zbi'},
          {'name': 'storage-full',
          'type': 'blk',
          'path': 'fvm.blk'},
          {'name': 'storage-sparse',
          'type': 'blk',
          'path': 'fvm.sparse.blk'},
          {'name': 'qemu-kernel',
          'type': 'bin',
          'path': 'boot.bin'},
          {'name': 'efi',
          'type': 'blk',
          'path': 'efi.blk'},
          {'name': 'netboot',
          'type': 'zbi',
          'path': 'netboot.zbi'},
      ]

    if has_data_template:
      return self.step_data('read image manifest', self.m.json.output(mock_image_manifest
        + [{'name': 'data-template',
          'type': 'blk',
          'path': 'fvm.data.sparse.blk'},]))
    else:
      return self.step_data('read image manifest', self.m.json.output(mock_image_manifest))

  def task_step_data(self,
                     output='',
                     device=False,
                     task_failure=False,
                     infra_failure=False,
                     expired=False,
                     no_resource=False,
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
      expired (bool): Whether the task expired waiting for live bots to become
        available and pick up the task.
      no_resource (bool): Whether the task exited because no resource (bot) was
        available to run the task.

    Returns:
      RecipeTestApi.step_data for the collect step.
    """
    task_datum = None
    outputs = ['out.tar'] if device else ['output.fs']
    if task_failure:
      task_datum = self.m.swarming.task_failure(output=output, outputs=outputs)
    elif infra_failure:
      # Don't allow setting output because we don't have a use case for it
      # and we need to maintain full line coverage
      assert not output
      task_datum = self.m.swarming.task_infra_failure(outputs=outputs)
    elif timed_out:
      task_datum = self.m.swarming.task_timed_out(
          output=output, outputs=outputs)
    elif expired:
      task_datum = self.m.swarming.task_expired()
    elif no_resource:
      task_datum = self.m.swarming.task_no_resource()
    else:
      task_datum = self.m.swarming.task_success(output=output, outputs=outputs)
    return self.step_data(
        'collect', self.m.swarming.collect(task_data=[task_datum]))

  def test_step_data(self, failure=False, host_results=False):
    """Returns mock step data for test results.

    This should be used by any test which calls api.fuchsia.test*() and expects
    it to make it to the tests analysis phase.

    Args:
      failure (bool): Whether a test failed or not.
      host_results (bool): Whether mock step data is being return for host tests

    Returns:
      RecipeTestApi.step_data for the extract_results step.
    """
    result = 'FAIL' if failure else 'PASS'

    # Host Results locally and do not require an 'extract results' step.
    step_name = 'run host tests' if host_results else 'extract results'

    test_name_prefix = '[START_DIR]' if host_results else ''
    summary_json = self.m.json.dumps({
        'tests': [{
            'name': '%s/hello' % test_name_prefix,
            'output_file': 'hello.out',
            'result': result
        }, {
            'name': 'benchmark.catapult_json',
            'output_file': 'benchmark.catapult_json',
            'result': result
        }],
        'outputs': {
            'goodbye-txt': 'goodbye.txt'
        }
    })
    return self.step_data(
        step_name,
        self.m.raw_io.output_dir({
            'summary.json': summary_json,
            'hello.out': 'hello',
            'goodbye.txt': 'goodbye',
            'benchmark.catapult_json': '["dummy_catapult_data"]',
        }))

  def secrets_step_data(self):
    """Returns mock step data for the secrets pipeline.

    This should be used by any test which calls api.fuchsia.test() with
    requires_secrets is set to True.

    Returns:
      list(RecipeTestApi.step_data) for the steps around secrets decryption.
    """
    step_data = []
    secret_name = 'auth-token'
    step_data.append(self.step_data(
        'process secret specs.list',
        self.m.file.listdir([
            '%s.json' % secret_name,
            'ciphertext' # the 'ciphertext' subdir, which will be skipped.
        ])
    ))
    step_data.append(self.step_data(
        'process secret specs.read spec for %s' % secret_name,
        self.m.json.output({
            'cloudkms_key_path': 'key-path',
        })
    ))
    step_data.append(self.step_data(
        'process secret specs.decrypt secret for %s' % secret_name,
        self.m.raw_io.output_text('plaintext')
    ))
    return step_data

