# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'catapult',
]


def RunSteps(api):
  # First, ensure we have catapult.
  api.catapult.ensure_catapult()
  api.catapult('help')

  api.catapult.make_histogram(
      'example_input_file',
      test_suite='example.suite',
      builder='example.builder',
      bucket='example.bucket',
      datetime=123456789,
  )

  api.catapult.upload(
      'example_input_file',
      service_account_json='example.json',
      url='https://example.com',
      timeout='30s',
  )


def GenTests(api):
  yield api.test('basic')
