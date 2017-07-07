# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Go toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/cipd',
  'infra/go',
  'infra/gsutil',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote):
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()
  api.go.ensure_go()

  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote)
    api.jiri.clean()
    update_result = api.jiri.update()
    revision = api.jiri.project('third_party/go').json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  go_dir = api.path['start_dir'].join('third_party', 'go')
  with api.context(cwd=go_dir.join('src'),
                   env={'GOROOT_BOOTSTRAP': api.go.go_root}):
    api.step('make', [go_dir.join('src', 'make.bash')])

  staging_dir = api.path.mkdtemp('go')
  pkg_dir = staging_dir.join('go')
  api.file.ensure_directory('create pkg dir', pkg_dir)
  for dir in ['bin', 'lib', 'pkg', 'src', 'misc']:
    api.file.copytree('copy %s' % dir, go_dir.join(dir), pkg_dir.join(dir))

  api.path.mock_add_paths(pkg_dir)
  assert api.path.exists(pkg_dir), (
    'Package directory %s does not exist' % (pkg_dir))

  go_version = api.file.read_text('read go version', go_dir.join('VERSION.cache'), test_data='go1.8')
  assert go_version, 'Cannot determine Go version'

  platform = '%s-%s' % (
      api.platform.name.replace('win', 'windows').replace('mac', 'darwin'),
      {
          32: '386',
          64: 'amd64',
      }[api.platform.bits],
  )

  cipd_pkg_name = 'fuchsia/go/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    return
  cipd_pkg_file = api.path['tmp_base'].join('go.cipd')

  api.cipd.build(
      input_dir=pkg_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'go_version': go_version,
        'git_repository': 'https://fuchsia.googlesource.com/third_party/go',
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('golang', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def GenTests(api):
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.properties(manifest='runtimes/go',
                          remote='https://fuchsia.googlesource.com/manifest'))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.properties(manifest='runtimes/go',
                          remote='https://fuchsia.googlesource.com/manifest') +
           api.step_data('cipd search fuchsia/go/%s-amd64 git_revision:%s' %
                         (platform, api.jiri.example_revision),
                         api.json.output({'result': []})))
