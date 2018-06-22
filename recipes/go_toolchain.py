# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Go toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/go',
  'infra/gsutil',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/step',
]

PROPERTIES = {
  'repository': Property(
      kind=str, help='Git repository URL to check out',
      default='https://fuchsia.googlesource.com/third_party/go'),
  'revision': Property(kind=str, help='Revision to check out', default=None),
}


def RunSteps(api, repository, revision):
  api.gsutil.ensure_gsutil()
  api.gitiles.ensure_gitiles()
  api.go.ensure_go(use_deprecated=True)

  cipd_pkg_name = 'fuchsia/go/' + api.cipd.platform_suffix()

  with api.context(infra_steps=True):
    if revision is None:
      revision = api.gitiles.refs(repository).get('refs/heads/master', None)
    step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  with api.context(infra_steps=True):
    go_dir = api.path['start_dir'].join('third_party', 'go')
    api.git.checkout(repository, go_dir, revision)

  with api.context(cwd=go_dir.join('src'),
                   env={'GOROOT_BOOTSTRAP': api.go.go_root}):
    api.step('build', [go_dir.join('src', 'make.bash')])

  pkg_dir = api.path['cleanup'].join('go.install')
  with api.step.nest('install'):
    api.file.ensure_directory('create pkg dir', pkg_dir)
    for dir in ['bin', 'lib', 'pkg', 'src', 'misc']:
      api.file.copytree('copy %s' % dir, go_dir.join(dir), pkg_dir.join(dir))

  api.path.mock_add_paths(pkg_dir)
  assert api.path.exists(pkg_dir), (
    'Package directory %s does not exist' % (pkg_dir))

  go_version = api.file.read_text('read go version',
                                  go_dir.join('VERSION.cache'),
                                  test_data='go1.8')
  assert go_version, 'Cannot determine Go version'

  cipd_pkg_file = api.path['cleanup'].join('go.cipd')
  api.cipd.build(
      input_dir=pkg_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy',
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': go_version,
        'git_repository': repository,
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('go', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def GenTests(api):
  go_rev = 'c6c554304e6d268f34ed510a36e77071830352cc'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', go_rev)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', go_rev)) +
           api.step_data('cipd search fuchsia/go/%s-amd64 git_revision:%s' %
                         (platform, go_rev),
                         api.json.output({'result': []})))
