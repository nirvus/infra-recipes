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
  'recipe_engine/buildbucket',
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
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=str, help='Target to build'),
}


def UploadPackage(api, revision, staging_dir):
  api.gsutil.ensure_gsutil()

  cipd_pkg_name = 'fuchsia/tools/jiri/' + api.cipd.platform_suffix()

  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    return

  cipd_pkg_file = api.path['cleanup'].join('jiri.cipd')

  api.cipd.build(
      input_dir=staging_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy',
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


def RunSteps(api, manifest, remote, target):
  api.jiri.ensure_jiri()
  api.go.ensure_go()

  build_input = api.buildbucket.build.input
  revision = build_input.gitiles_commit.id

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest=manifest,
                      remote=remote,
                      # jiri manifest lives in fuchsia/manifests, if this
                      # is a CI build, we just want to checkout at HEAD
                      build_input=None if revision else build_input)

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
    assert revision
    UploadPackage(api, revision, staging_dir)


def GenTests(api):
  revision = 'a1b2c3'

  yield (api.test('ci') +
    api.buildbucket.ci_build(
      git_repo='https://fuchsia.googlesource.com/jiri',
      revision=revision,
    ) +
    api.properties(manifest='jiri',
                   remote='https://fuchsia.googlesource.com/manifest',
                   target='linux-amd64'))
  yield (api.test('ci_new') +
    api.buildbucket.ci_build(
      git_repo='https://fuchsia.googlesource.com/jiri',
      revision=revision,
    ) +
    api.properties(manifest='jiri',
                   remote='https://fuchsia.googlesource.com/manifest',
                   target='linux-amd64') +
    api.step_data('cipd search fuchsia/tools/jiri/linux-amd64 git_revision:' +
                  revision,
                  api.json.output({'result': []})))
  yield (api.test('cq_try') +
    api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/jiri'
    ) +
    api.properties.tryserver(
        manifest='jiri',
        remote='https://fuchsia.googlesource.com/manifest',
        target='linux-amd64',
        tryjob=True))
