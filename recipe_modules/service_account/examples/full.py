# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'service_account',
]


def RunSteps(api):
  api.service_account.get_json_path('test')


def GenTests(api):
  yield api.test('basic')
