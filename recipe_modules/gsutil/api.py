# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

import re


class GSUtilApi(recipe_api.RecipeApi):
  """GSUtilApi provides support for GSUtil."""

  def __init__(self, *args, **kwargs):
    super(GSUtilApi, self).__init__(*args, **kwargs)
    self._gsutil_tool = None

  def __call__(self, *args, **kwargs):
    """Return a step to run arbitrary gsutil command."""
    assert self._gsutil_tool
    name = kwargs.pop('name', 'gsutil ' + args[0])
    infra_step = kwargs.pop('infra_step', True)
    cmd_prefix = []
    # Note that metadata arguments have to be passed before the command.
    metadata = kwargs.pop('metadata', [])
    if metadata:
      for k, v in sorted(metadata.iteritems(), key=lambda (k, _): k):
        field = self._get_metadata_field(k)
        param = (field) if v is None else ('%s:%s' % (field, v))
        cmd_prefix.extend(['-h', param])
    if kwargs.pop('parallel_upload', False):
      cmd_prefix.extend([
        '-o',
        'GSUtil:parallel_composite_upload_threshold=50M'
      ])
    if kwargs.pop('multithreaded', False):
      cmd_prefix.extend(['-m'])
    cmd_prefix.extend([
      '-o',
      'GSUtil:software_update_check_period=0',
    ])
    return self.m.python(name, self._gsutil_tool, cmd_prefix + list(args),
                         venv=self.resource('gsutil.vpython'),
                         infra_step=infra_step, **kwargs)

  @recipe_api.non_step
  def normalize(self, url):
    """Normalize a GS URL using the gs:// URL prefix."""
    gs_prefix = 'gs://'
    # Defines the regex that matches a normalized URL.
    for prefix in (
      gs_prefix,
      'https://storage.cloud.google.com/',
      'https://storage.googleapis.com/',
      ):
      if url.startswith(prefix):
        return gs_prefix + url[len(prefix):]
    raise AssertionError("%s cannot be normalized" % url)

  @recipe_api.non_step
  def join(self, *parts):
    """Constructs a GS path from composite parts."""
    return '/'.join(p.strip('/') for p in parts)

  @classmethod
  def _http_url(cls, bucket, dest, unauthenticated_url=False):
    if unauthenticated_url:
      base = 'https://storage.googleapis.com/%s/%s'
    else:
      base = 'https://storage.cloud.google.com/%s/%s'
    return base % (bucket, dest)

  @staticmethod
  def _get_metadata_field(name, provider_prefix=None):
    """Returns: (str) the metadata field to use with Google Storage

    The Google Storage specification for metadata can be found at:
    https://developers.google.com/storage/docs/gsutil/addlhelp/WorkingWithObjectMetadata
    """
    # Already contains custom provider prefix
    if name.lower().startswith('x-'):
      return name

    # See if it's innately supported by Google Storage
    if name in (
      'Cache-Control',
      'Content-Disposition',
      'Content-Encoding',
      'Content-Language',
      'Content-MD5',
      'Content-Type',
      ):
      return name

    # Add provider prefix
    if not provider_prefix:
      provider_prefix = 'x-goog-meta'
    return '%s-%s' % (provider_prefix, name)

  def ensure_gsutil(self, version=None):
    if self._gsutil_tool:
      return self._gsutil_tool

    with self.m.step.nest('ensure_gsutil'):
      with self.m.context(infra_steps=True):
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('infra/tools/gsutil', version or 'latest')
        cipd_dir = self.m.path['start_dir'].join('cipd', 'gsutil')
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._gsutil_tool = cipd_dir.join('gsutil')
        return self._gsutil_tool

  def upload(self, bucket, src, dst, link_name='gsutil.upload',
             unauthenticated_url=False, **kwargs):
    step = self('cp', src, 'gs://%s/%s' % (bucket, dst), **kwargs)
    if link_name:
      step.presentation.links[link_name] = self._http_url(
          bucket, dst, unauthenticated_url=unauthenticated_url)
    return step

  def copy(self, src_bucket, src, dst_bucket, dst, link_name='gsutil.copy',
           unauthenticated_url=False, **kwargs):
    step = self('cp',
        'gs://%s/%s' % (src_bucket, src),
        'gs://%s/%s' % (dst_bucket, dst),
        **kwargs)
    if link_name:
      step.presentation.links[link_name] = self._http_url(
          dst_bucket, dst, unauthenticated_url=unauthenticated_url)
    return step
