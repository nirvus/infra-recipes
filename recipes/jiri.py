# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Jiri."""

from recipe_engine.recipe_api import Property
from recipe_engine import config


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'infra/git',
  'infra/go',
  'infra/gsutil',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/time',
]

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                            default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=str, help='Target to build'),
}


def UploadPackage(api, revision, staging_dir):
  api.gsutil.ensure_gsutil()

  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  cipd_pkg_name = 'fuchsia/tools/jiri/' + api.cipd.platform_suffix()

  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    return

  cipd_pkg_file = api.path['tmp_base'].join('jiri.cipd')

  api.cipd.build(
      input_dir=staging_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'git_repository': 'https://fuchsia.googlesource.com/jiri',
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('jiri', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target):
  api.jiri.ensure_jiri()
  api.go.ensure_go()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    revision = api.jiri.project(['jiri']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  staging_dir = api.path.mkdtemp('jiri')
  jiri_dir = api.path['start_dir'].join(
      'go', 'src', 'fuchsia.googlesource.com', 'jiri')

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
        'infra/cmake/${platform}': 'version:3.9.1',
        'infra/ninja/${platform}': 'version:1.7.2',
      })

  env = {
    'CMAKE_PROGRAM': cipd_dir.join('bin', 'cmake'),
    'NINJA_PROGRAM': cipd_dir.join('ninja'),
    'GO_PROGRAM': api.go.go_executable
  }
  with api.context(cwd=staging_dir, env=env):
    api.step('build jiri', [jiri_dir.join('scripts', 'build.sh')])

  gopath = api.path['start_dir'].join('go')
  with api.context(env={'GOPATH': gopath}):
    api.go('test', 'fuchsia.googlesource.com/jiri/cmd/jiri')

  if not api.properties.get('tryjob', False):
    UploadPackage(api, revision, staging_dir)


def GenTests(api):
  yield (api.test('ci') +
    api.properties(manifest='jiri',
                   remote='https://fuchsia.googlesource.com/manifest',
                   target='linux-amd64'))
  yield (api.test('ci_new') +
    api.properties(manifest='jiri',
                   remote='https://fuchsia.googlesource.com/manifest',
                   target='linux-amd64') +
    api.step_data('cipd search fuchsia/tools/jiri/linux-amd64 git_revision:' +
                  api.jiri.example_revision,
                  api.json.output({'result': []})))
  yield (api.test('cq_try') +
    api.properties.tryserver(
        gerrit_project='jiri',
        patch_gerrit_url='fuchsia-review.googlesource.com',
        manifest='jiri',
        remote='https://fuchsia.googlesource.com/manifest',
        target='linux-amd64',
        tryjob=True))
