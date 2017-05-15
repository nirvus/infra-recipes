# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Rust toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gsutil',
  'infra/tar',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/shutil',
  'recipe_engine/step',
  'recipe_engine/tempfile',
  'recipe_engine/url',
]

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
}

RUST_GIT = 'https://github.com/rust-lang/rust'
RUST_BUILDS = 'https://s3.amazonaws.com/rust-lang-ci/rustc-builds/'
RUST_BUILDS_ALT = 'https://s3.amazonaws.com/rust-lang-ci/rustc-builds-alt/'

GIT_HASH_RE = re.compile('([0-9a-f]{40})', re.IGNORECASE)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url):
  api.tar.ensure_tar()
  api.gsutil.ensure_gsutil()

  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  staging_dir = api.path.mkdtemp('rust')

  step = api.git('ls-remote', RUST_GIT, 'refs/heads/master',
      stdout=api.raw_io.output())
  sha = GIT_HASH_RE.search(step.stdout).group(1)

  target = '%s-%s' % (
    {
      32: 'i686',
      64: 'x86_64',
    }[api.platform.bits],
    {
      'linux': 'unknown-linux-gnu',
      'mac': 'apple-darwin',
    }[api.platform.name],
  )
  rust_nightly = 'rust-nightly-' + target
  rust_nightly_filename = 'rust-nightly-%s.tar.gz' % target
  rust_nightly_archive = staging_dir.join(rust_nightly_filename)
  api.url.get_file(RUST_BUILDS_ALT + sha + '/' + rust_nightly_filename, rust_nightly_archive)

  rust_dir = staging_dir.join('rust-%s' % target)
  api.tar.extract('extract rust', rust_nightly_archive, dir=staging_dir)
  api.step('install rust',
      [staging_dir.join(rust_nightly, 'install.sh'), '--prefix=%s' % rust_dir])

  for target in ['x86_64-unknown-fuchsia', 'aarch64-unknown-fuchsia']:
    rust_std_nightly = 'rust-std-nightly-' + target
    rust_std_nightly_filename = 'rust-std-nightly-%s.tar.gz' % target
    rust_std_nightly_archive = staging_dir.join(rust_nightly_filename)
    api.url.get_file(RUST_BUILDS + sha + '/' + rust_std_nightly_filename, rust_std_nightly_archive)

    api.tar.extract('extract %s rust-std' % target, rust_std_nightly_archive, dir=staging_dir)
    api.step('install %s rust-std' % target,
        [staging_dir.join(rust_std_nightly, 'install.sh'), '--prefix=%s' % rust_dir])

  for f in api.shutil.glob('glob', rust_dir.join('**/manifest-*'),
                           test_data=[rust_dir.join('lib/rustlib/manifest-rustc')]):
    api.shutil.remove('remove %s' % f, f)

  step_result = api.step('rust version',
      [rust_dir.join('bin', 'rustc'), '--version'],
      stdout=api.raw_io.output(),
      step_test_data=lambda:
      api.raw_io.test_api.stream_output('rustc 1.19.0-nightly (75b056812 2017-05-15)'))
  m = re.search(r'rustc ([0-9a-z.-]+)', step_result.stdout)
  assert m, 'Cannot determine Rust version'
  rust_version = m.group(1)

  cipd_pkg_name = 'fuchsia/rust/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + sha)
  if step.json.output['result']:
    return
  cipd_pkg_file = staging_dir.join('rust.cipd')

  api.cipd.build(
      input_dir=rust_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'rust_version': rust_version,
        'git_repository': RUST_GIT,
        'git_revision': sha,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('rust', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.step_data('git ls-remote', api.raw_io.stream_output(revision)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.step_data('git ls-remote', api.raw_io.stream_output(revision)) +
           api.step_data('cipd search fuchsia/rust/' + platform + '-amd64 ' +
                         'git_revision:' + revision,
                         api.json.output({'result': []})))
