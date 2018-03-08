# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'catapult',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  # First, ensure we have catapult.
  api.catapult.ensure_catapult()
  api.catapult('help')

  histogram_set_data = api.catapult.make_histogram(
      'example_input_file',
      test_suite='example.suite',
      builder='example.builder',
      bucket='example.bucket',
      datetime=123456789,
      # Verify kwargs are passed to the generated step
      stdout=api.raw_io.output('out'),
      step_test_data=(
          lambda: api.raw_io.test_api.stream_output('{HISTOGRAM_SET}')),
  ).stdout
  assert histogram_set_data == '{HISTOGRAM_SET}'

  result = api.catapult.upload(
      'example_input_file',
      url='https://example.com',
      timeout='30s',
      # Verify kwargs are passed to the generated step
      stdout=api.raw_io.output('out'),
      step_test_data=(lambda: api.raw_io.test_api.stream_output('success!')),
  ).stdout
  assert result == 'success!'

  # Upload without timeout.
  api.catapult.upload(
      'example_input_file',
      url='http://example.com',
  )


def GenTests(api):
  yield api.test('basic')
