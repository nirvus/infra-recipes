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
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
}

# The current list of platforms that we build for.
GO_OS_ARCH = (
    ('linux', 'amd64'),
    ('linux', 'arm64'),
    ('darwin', 'amd64'),
)


def upload_package(api, name, platform, staging_dir, revision, remote):
  cipd_pkg_name = 'fuchsia/tools/%s/%s' % (name, platform)
  api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if api.step.active_result.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=staging_dir,
      install_mode='copy',
  )
  pkg_def.add_file(staging_dir.join(name))
  pkg_def.add_version_file('.versions/%s.cipd_version' % name)

  cipd_pkg_file = api.path['cleanup'].join('%s.cipd' % name)
  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'git_repository': remote,
          'git_revision': revision,
      },
  )


def RunSteps(api, project, manifest, remote):
  api.jiri.ensure_jiri()
  api.go.ensure_go()
  api.gsutil.ensure_gsutil()

  build_input = api.buildbucket.build.input

  with api.context(infra_steps=True):
    api.jiri.checkout(
        manifest=manifest,
        remote=remote,
        project=project,
        build_input=build_input)

  staging_dir = api.path.mkdtemp('jiri')

  gopath = api.path['start_dir'].join('go')
  with api.context(env={'GOPATH': gopath}):
    # Run all the tests.
    api.go('test', '-v', 'fuchsia.googlesource.com/jiri/...')

    for goos, goarch in GO_OS_ARCH:
      with api.context(env={'GOOS': goos, 'GOARCH': goarch}):
        platform = '%s-%s' % (goos.replace('darwin', 'mac'), goarch)

        with api.step.nest(platform):
          args = [
            'build', '-v', '-o', staging_dir.join('jiri'),
            'fuchsia.googlesource.com/jiri/cmd/jiri'
          ]

          if not api.properties.get('tryjob', False):
            revision = build_input.gitiles_commit.id
            assert revision

            build_time = api.time.utcnow().isoformat()
            ldflags = ' '.join([
              '-X "fuchsia.googlesource.com/jiri/version.GitCommit=%s"' % revision,
              '-X "fuchsia.googlesource.com/jiri/version.BuildTime=%s"' % build_time,
            ])

            args += ['-ldflags', ldflags]

          # Build the package.
          api.go(*args)

          if not api.properties.get('tryjob', False):
            upload_package(api, 'jiri', platform, staging_dir, revision, remote)

            api.gsutil.upload(
                'fuchsia-build',
                staging_dir.join('jiri'),
                api.gsutil.join('jiri', '%s-%s' % (goos, goarch), revision),
                unauthenticated_url=True,
                ok_ret=(0, 1),
            )


def GenTests(api):
  revision = 'a1b2c3'
  cipd_search_step_data = []
  for goos, goarch in GO_OS_ARCH:
    platform = '%s-%s' % (goos.replace('darwin', 'mac'), goarch)
    cipd_search_step_data.append(
        api.step_data(
            '{0}.cipd search fuchsia/tools/jiri/{0} git_revision:{1}'.
            format(platform, revision),
            api.json.output({
                'result': []
            })))

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
    reduce(lambda a, b: a + b, cipd_search_step_data))
  yield (api.test('cq_try') +
    api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/jiri'
    ) +
    api.properties.tryserver(
        manifest='jiri',
        remote='https://fuchsia.googlesource.com/manifest',
        target='linux-amd64',
        tryjob=True))
