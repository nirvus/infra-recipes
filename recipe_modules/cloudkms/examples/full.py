# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cloudkms',
    'recipe_engine/path',
    'recipe_engine/raw_io',
]

def RunSteps(api):
  # Ensure that the CloudKMS client is installed.
  api.cloudkms.ensure_cloudkms()

  # Decrypt ciphertext.txt with crypto/key/path to plaintext.txt.
  api.cloudkms.decrypt('decrypt secret',
                       'crypto/key/path',
                       api.path['start_dir'].join('ciphertext.txt'),
                       api.path['start_dir'].join('plaintext.txt'))

def GenTests(api):
  plaintext_data = api.step_data(
      'decrypt secret',
      api.raw_io.output('Shh! I am a secret'),
  )

  yield api.test('decryption') + plaintext_data
