# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class GerritApi(recipe_api.RecipeApi):
  """Module for querying a Gerrit host through the Gerrit API."""

  def __init__(self, gerrit_host, *args, **kwargs):
    super(GerritApi, self).__init__(*args, **kwargs)
    self._gerrit_host = gerrit_host
    self._gerrit_path = None

  def __call__(self, name, subcmd, input_json, gerrit_host=None,
               test_data=None):
    assert self._gerrit_path
    if not gerrit_host:
      assert self._gerrit_host
      gerrit_host = self._gerrit_host
    cmd = [
      self._gerrit_path,
      subcmd,
      '-host', gerrit_host,
      '-input', self.m.json.input(input_json),
      '-output', self.m.json.output(),
    ]

    # If there's test data, create a factory for it.
    step_test_data = None
    if test_data is not None:
      step_test_data = lambda: test_data

    # Run the gerrit client command.
    return self.m.step(
        name,
        cmd,
        step_test_data=step_test_data,
    ).json.output

  def ensure_gerrit(self, version=None):
    with self.m.step.nest('ensure_gerrit'):
      with self.m.context(infra_steps=True):
        gerrit_package = ('infra/tools/luci/gerrit/%s' %
            self.m.cipd.platform_suffix())
        gerrit_dir = self.m.path['start_dir'].join('cipd', 'gerrit')

        self.m.cipd.ensure(
            gerrit_dir, {gerrit_package: version or 'latest'})
        self._gerrit_path = gerrit_dir.join('gerrit')

        return self._gerrit_path

  @property
  def host(self):
    return self._gerrit_host

  @host.setter
  def host(self, host):
    self._gerrit_host = host

  def abandon(self, name, change_id, message=None, test_data=None):
    """Abandons a change.

    Returns the details of the change, after attempting to abandon.

    Args:
      name (str): The name of the step.
      change_id (str): A change ID that uniquely defines a change on the host.
      message (str): A message explaining the reason for abandoning the change.
      test_data (recipe_test_api.StepTestData): Test JSON output data for this step.
    """
    input_json = {'change_id': change_id}
    if message:
      input_json['input'] = {'message': message}
    return self(
        name=name,
        subcmd='change-abandon',
        input_json=input_json,
        test_data=test_data,
    )

  def create_change(self, name, project, subject, branch, topic=None,
                    test_data=None):
    """Creates a new change for a given project on the gerrit host.

    Returns the details of the newly-created change.

    Args:
      name (str): The name of the step.
      project (str): The name of the project on the host to create a change for.
      subject (str): The subject of the new change.
      branch (str): The branch onto which the change will be made.
      topic (str): A gerrit topic that can be used to atomically land the change with
        other changes in the same topic.
      test_data (recipe_test_api.StepTestData): Test JSON output data for this step.
    """
    input_json = {'input': {
      'project': project,
      'subject': subject,
      'branch': branch,
    }}
    if topic:
      input_json['input']['topic'] = topic
    return self(
        name=name,
        subcmd='change-create',
        input_json=input_json,
        test_data=test_data,
    )

  def set_review(self, name, change_id, labels=None, reviewers=None,
                 ccs=None, revision='current', test_data=None):
    """Sets a change at a revision for review. Can optionally set labels,
    reviewers, and CCs.

    Returns updated labels, reviewers, and whether the change is ready for
    review as a JSON dict.

    Args:
      name (str): The name of the step.
      change_id (str): A change ID that uniquely defines a change on the host.
      labels (dict): A map of labels (with names as strings, e.g. 'Code-Review') to the
        integral values you wish to set them to.
      reviewers (list): A list of strings containing reviewer IDs (e.g. email addresses).
      ccs (list): A list of strings containing reviewer IDs (e.g. email addresses).
      revision (str): A revision ID that identifies a revision for the change
        (default is 'current').
      test_data (recipe_test_api.StepTestData): Test JSON output data for this step.
    """
    input_json = {
      'change_id': change_id,
      'revision_id': revision,
      'input': {}
    }
    if labels:
      input_json['input']['labels'] = labels
    if reviewers or ccs:
      input_json['input']['reviewers'] = []
    if reviewers:
      input_json['input']['reviewers'] += [{'reviewer': i} for i in reviewers]
    if ccs:
      input_json['input']['reviewers'] += [{'reviewer': i, 'state': 'CC'} for i in ccs]
    return self(
        name=name,
        subcmd='set-review',
        input_json=input_json,
        test_data=test_data,
    )

  def change_details(self, name, change_id, gerrit_host=None, test_data=None):
    """Returns a JSON dict of details regarding a specific change.

    Args:
      name (str): The name of the step.
      change_id (str): A change ID that uniquely defines a change on the host.
      gerrit_host (str): The Gerrit host to make the query against. Overrides
        the recipe module's global host property.
      test_data (recipe_test_api.StepTestData): Test JSON output data for this
        step.
    """
    return self(
        name=name,
        subcmd='change-detail',
        input_json={'change_id': change_id},
        gerrit_host=gerrit_host,
        test_data=test_data,
    )

  # TODO(IN-625): Get this value from the Gerrit client.
  def get_change_ref(self, change, patchset):
    """Returns the reference ID to a given Gerrit change.

    Args:
      change (int): Change number.
      patchset (int): Patch set number.
    """
    assert change >= 0 and patchset >= 0
    last_two_digits = str(change)[-2:]
    return 'refs/changes/%s/%d/%d' % (last_two_digits, change, patchset)
