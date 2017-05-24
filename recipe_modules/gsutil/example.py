# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'gsutil',
  'recipe_engine/path',
]


def RunSteps(api):
  api.gsutil.ensure_gsutil()
  api.gsutil.set_boto_config('/creds/.boto')

  local_file = api.path['tmp_base'].join('file')
  bucket = 'example'
  cloud_file = api.gsutil.join('path/', 'to', 'file/')

  api.gsutil.upload(bucket, local_file, cloud_file,
      metadata={
        'Test-Field': 'value',
        'Remove-Me': None,
        'x-custom-field': 'custom-value',
        'Cache-Control': 'no-cache',
      },
      unauthenticated_url=True)

  # Upload in parallel.
  api.gsutil.upload(bucket, local_file, cloud_file,
      metadata={
        'Test-Field': 'value',
        'Remove-Me': None,
        'x-custom-field': 'custom-value',
        'Cache-Control': 'no-cache',
      },
      unauthenticated_url=True,
      parallel_upload=True,
      multithreaded=True)

  api.gsutil('cp',
      'gs://%s/some/random/path/**' % bucket,
      'gs://%s/staging' % bucket)

  api.gsutil('cp',
      api.gsutil.normalize('https://storage.cloud.google.com/' + bucket + '/' + cloud_file),
      local_file,
      name='gsutil download url')

  # Non-normalized URL.
  try:
    api.gsutil('cp',
        api.gsutil.normalize('https://someotherservice.localhost'),
        local_file,
        name='gsutil download url')
  except AssertionError:
    pass

  new_cloud_file = 'staging/to/file'
  new_local_file = api.path['tmp_base'].join('erang')
  api.gsutil('cp', 'gs://%s/%s' % (bucket, new_cloud_file), new_local_file)

  private_key_file = 'path/to/key'
  _signed_url = api.gsutil('signurl', private_key_file, bucket, cloud_file)
  api.gsutil('rm', 'gs://%s/%s' % (bucket, new_cloud_file))

  api.gsutil('ls', 'gs://%s/foo' % bucket)
  api.gsutil.copy(bucket, cloud_file, bucket, new_cloud_file)

  api.gsutil('cat', 'gs://%s/foo' % bucket)


def GenTests(api):
  yield api.test('basic')
