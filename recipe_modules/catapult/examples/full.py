# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'catapult',
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'recipe_engine/json',
]


def RunSteps(api):
  api.catapult.ensure_catapult()

  # Show help.
  api.catapult('help')

  # Generate a histogram set from some input file.
  api.catapult.make_histogram(
      input_file=api.json.input({}),
      test_suite='example.suite',
      masters_name='dashboard_masters_name',
      bots_name='dashboard_bots_name',
      execution_timestamp_ms=123456789,
      output_file=api.json.output(name='histogram_set'),
      log_url="https://ci.chromium.org/logs",
  )

  histogram_set_data = api.file.read_text(
      name='read_histogam',
      source=api.json.input({}),
      test_data='{HISTOGRAM_SET}',
  )
  assert histogram_set_data == '{HISTOGRAM_SET}'

  # Upload a histogram set to the Catapult dashboard.
  result = api.catapult.upload(
      input_file=api.json.input({}),
      url='https://example.com',
      timeout='30s',
      # Verify kwargs are passed to the generated step
      stdout=api.raw_io.output(),
      step_test_data=(lambda: api.raw_io.test_api.stream_output('success!')),
  ).stdout
  assert result == 'success!'

  # Upload a histogram set without timeout.
  api.catapult.upload(input_file=api.json.input({}), url='http://example.com')


def GenTests(api):
  yield api.test('basic')
