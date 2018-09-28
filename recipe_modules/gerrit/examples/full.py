# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'gerrit',
    'recipe_engine/json',
    'recipe_engine/properties',
]


def RunSteps(api):
  api.gerrit.ensure_gerrit()
  api.gerrit.host = 'https://fuchsia-review.googlesource.com'
  assert api.gerrit.host == 'https://fuchsia-review.googlesource.com'

  # Create a change.
  change = api.gerrit.create_change(
      'create change',
      'infra/config',
      'hello',
      'master',
      topic='some-topic',
      test_data=api.json.test_api.output({'id': 'some id'}),
  )
  change_id = change['id']

  # Get change details.
  api.gerrit.change_details('get details', change_id)

  # Change details can override the Gerrit host.
  api.gerrit.change_details(
      name='get details',
      change_id=change_id,
      gerrit_host='https://chromium-review.googlesource.com',
  )

  # Get change details with specific query parameters.
  api.gerrit.change_details(
      name='get details',
      change_id=change_id,
      query_params=['CURRENT_REVISION', 'DOWNLOAD_COMMANDS'],
  )

  # Set review.
  api.gerrit.set_review(
      '-1',
      change_id,
      labels = {'Code-Review': -1},
      reviewers = ['test@example.com'],
      ccs = ['test2@example.com'],
  )

  # Abandon.
  api.gerrit.abandon('abandon', change_id, message='bad CL')


def GenTests(api):
  yield api.test('basic')
