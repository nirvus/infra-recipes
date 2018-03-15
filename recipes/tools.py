# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building and publishing tools."""

from recipe_engine.recipe_api import Property
from recipe_engine.config import List
from recipe_engine import config

import os

DEPS = [
    'infra/cipd',
    'infra/jiri',
    'infra/git',
    'infra/go',
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
    'category':
        Property(kind=str, help='Build category', default=None),
    'patch_gerrit_url':
        Property(kind=str, help='Gerrit host', default=None),
    'patch_project':
        Property(kind=str, help='Gerrit project', default=None),
    'patch_ref':
        Property(kind=str, help='Gerrit patch ref', default=None),
    'patch_storage':
        Property(kind=str, help='Patch location', default=None),
    'patch_repository_url':
        Property(kind=str, help='URL to a Git repository', default=None),
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
    'revision':
        Property(kind=str, help='Revision', default=None),
    'target':
        Property(kind=str, help='CIPD target to build', default=None),
    'packages':
        Property(kind=List(str), help='The list of Go packages to build'),
}


def UploadPackage(api, name, target, staging_dir, revision, remote):
  cipd_pkg_name = 'fuchsia/tools/%s/%s' % (name, target)
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=staging_dir,)
  pkg_def.add_file(staging_dir.join(name))

  api.cipd.create_from_pkg(
      pkg_def,
      refs=['latest'],
      tags={
          'git_repository': remote,
          'git_revision': revision,
      },)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             revision, target, packages):
  api.jiri.ensure_jiri()
  api.go.ensure_go()

  if not target:
    target = '%s-%s' % (api.platform.name.replace('win', 'windows'), {
        'intel': {
            32: '386',
            64: 'amd64',
        },
        'arm': {
            32: 'armv6',
            64: 'arm64',
        },
    }[api.platform.arch][api.platform.bits])

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    if not revision:
      revision = api.jiri.project([project]).json.output[0]['revision']

  with api.context(infra_steps=True):
    cipd_dir = api.path['start_dir'].join('cipd')
    api.cipd.ensure(cipd_dir, {
        'go/cmd/github.com/golang/dep/${platform}': 'version:0.3.2',
    })

  gopath = api.path['start_dir'].join('go')

  path = api.jiri.project([project]).json.output[0]['path']
  with api.context(cwd=api.path.abs_to_path(path), env={'GOPATH': gopath}):
    # Ensure all dependencies are present.
    api.step('dep ensure',
             [cipd_dir.join('dep'), 'ensure', '-v', '-vendor-only'])

    # Run all the tests.
    api.go('test', '-v', './...')

  staging_dir = api.path.mkdtemp('tools')
  goos, goarch = target.split('-')

  with api.context(
      cwd=staging_dir, env={'GOPATH': gopath,
                            'GOOS': goos,
                            'GOARCH': goarch}):
    for pkg in packages:
      # Build the package.
      api.go('build', '-v', pkg)

      if not api.properties.get('tryjob', False):
        # Upload the package to CIPD.
        UploadPackage(api,
                      pkg.split('/')[-1], target, staging_dir, revision, remote)


def GenTests(api):
  revision = 'c22471f4e3f842ae18dd9adec82ed9eb78ed1127'
  target = 'linux-amd64'
  yield (api.test('ci_new') + api.properties(
      project='tools',
      manifest='tools',
      remote='https://fuchsia.googlesource.com/tools',
      target=target,
      packages=['fuchsia.googlesource.com/tools/cmd/symbolizer']) +
         api.step_data(
             'cipd search fuchsia/tools/symbolizer/' + target + ' git_revision:'
             + revision,
             api.json.output({
                 'result': []
             }),))
  yield (api.test('ci') + api.properties(
      project='tools',
      manifest='tools',
      remote='https://fuchsia.googlesource.com/tools',
      packages=['fuchsia.googlesource.com/tools/cmd/symbolizer']))
  yield (api.test('cq_try') + api.properties(
      project='tools',
      manifest='tools',
      tryjob=True,
      remote='https://fuchsia.googlesource.com/tools',
      target=target,
      packages=['fuchsia.googlesource.com/tools/cmd/symbolizer']))
