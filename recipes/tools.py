# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building and publishing tools."""

from recipe_engine.recipe_api import Property
from recipe_engine.config import List
from recipe_engine import config

from collections import namedtuple

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
    'recipe_engine/url',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = {
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
    'packages':
        Property(kind=List(str), help='The list of Go packages to build'),
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

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('tools', name,
                      api.cipd.platform_suffix(),
                      step_result.json.output['result']['instance_id']),
      unauthenticated_url=True,
      ok_ret=(0, 1),
  )


def RunSteps(api, project, manifest, remote, packages):
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
    revision = api.jiri.project([project]).json.output[0]['revision']

  gopath = api.path['start_dir'].join('go')
  path = api.jiri.project([project]).json.output[0]['path']
  staging_dir = api.path.mkdtemp('tools')

  with api.context(cwd=api.path.abs_to_path(path), env={'GOPATH': gopath}):
    # Run all the tests.
    api.go('test', '-v', './...')

    for goos, goarch in GO_OS_ARCH:
      with api.context(env={'GOOS': goos, 'GOARCH': goarch}):
        platform = '%s-%s' % (goos.replace('darwin', 'mac'), goarch)
        for pkg in packages:
          with api.step.nest(pkg), api.step.nest(platform):
            output = pkg.split('/')[-1]

            # Build the package.
            api.go('build', '-o', staging_dir.join(output), pkg)

            # Upload the package to CIPD.
            if not api.properties.get('tryjob', False):
              upload_package(api, output, platform, staging_dir, revision,
                             remote)


def GenTests(api):
  packages = [
      'fuchsia.googlesource.com/tools/gndoc',
      'fuchsia.googlesource.com/tools/symbolizer'
  ]
  cipd_search_step_data = []
  for goos, goarch in GO_OS_ARCH:
    for pkg in packages:
      platform = '%s-%s' % (goos.replace('darwin', 'mac'), goarch)
      cipd_search_step_data.append(
          api.step_data(
              '{0}.{1}.cipd search fuchsia/tools/{2}/{1} git_revision:{3}'.
              format(pkg, platform, pkg.split('/')[-1],
                     api.jiri.example_revision),
              api.json.output({
                  'result': []
              })))
  yield (api.test('ci_new') +
    api.buildbucket.ci_build(
        git_repo='https://fuchsia.googlesource.com/tools',
        revision = api.jiri.example_revision,
    ) +
    api.properties(
      project='tools',
      manifest='tools',
      remote='https://fuchsia.googlesource.com/tools',
      packages=packages
    ) +
    reduce(lambda a, b: a + b, cipd_search_step_data)
  )

  yield (api.test('ci') +
    api.buildbucket.ci_build(
        git_repo='https://fuchsia.googlesource.com/tools',
        revision=api.jiri.example_revision,
    ) +
    api.properties(
      project='tools',
      manifest='tools',
      remote='https://fuchsia.googlesource.com/tools',
      packages=packages)
  )

  yield (api.test('cq_try') +
    api.buildbucket.try_build(
        git_repo='https://fuchsia.googlesource.com/tools',
    ) +
    api.properties(
      project='tools',
      manifest='tools',
      remote='https://fuchsia.googlesource.com/tools',
      packages=packages,
      tryjob=True,
    )
  )
