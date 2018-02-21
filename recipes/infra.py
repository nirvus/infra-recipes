# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building and publishing infra tools.

This recipe builds one or more Go binaries in the specified project and
publishes them all to CIPD.  If one or more tests for any package in the
project fail, or one or more packages fail to build, execution stops and no
packages are uploaded.

This recipe uses golang/dep to manage dependencies, so the given project is
expected to have a Gopkg.toml file specifying its dependency restrictions.
"""

from recipe_engine.recipe_api import Property
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
}

# The tag referencing the golang/dep CIPD package used to install dependencies.
#
# Do not confuse this with the version of https://github.com/golang/dep itself.
# The CIPD package referenced by this version should provide the same version
# of https://github.com/golang/dep that is used for local development
DEP_VERSION = 'version:0.3.2'

# The Go import path for Fuchsia's infra tools project.
PKG_NAME = 'fuchsia.googlesource.com/infra/infra'

# The list of packages to build.
PACKAGES = set([PKG_NAME + '/cmd/catapult'])


def UploadPackage(api, bin_name, bin_dir, revision, remote):
  """
  Creates and uploads a CIPD package containing the tool at bin_dir/bin_name.

  The tool is published to CIPD under the path 'fuchsia/infra/$bin_name/$platform'

  Args:
    bin_dir: The absolute path to the parent directory of bin_name.
    bin_name: The name of the tool binary
  """
  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  cipd_pkg_name = 'fuchsia/infra/%s/%s' % (bin_name, api.cipd.platform_suffix())
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=bin_dir,
  )
  pkg_def.add_file(bin_dir.join(bin_name))

  api.cipd.create_from_pkg(
      pkg_def,
      refs=['latest'],
      tags={
          'git_repository': remote,
          'git_revision': revision,
      },
  )


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             revision):
  api.jiri.ensure_jiri()
  api.go.ensure_go()

  gopath = api.path['start_dir'].join('go')

  # Checkout the project at the specified patch.
  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)

  # Install golang/dep for dependencies.
  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
          'go/cmd/github.com/golang/dep/${platform}': DEP_VERSION,
      })

  with api.context(env={'GOPATH': gopath}):
    # A string representing the absolute path where Jiri places the project.
    abs_project_path = api.jiri.project([project]).json.output[0]['path']

    with api.context(cwd=api.path.abs_to_path(abs_project_path)):
      # Download dependencies.
      dep_exe = cipd_dir.join('dep')
      api.step('dep_ensure', [dep_exe, 'ensure', '-v'])

    # Run all tests in the project.
    api.go('test', api.url.join(PKG_NAME, '...'))

    bin_dir = api.path.mkdtemp('infra')

    # Build all tools.
    for pkg in PACKAGES:
      bin_name = pkg.split('/')[-1]
      api.go('build', '-o', bin_dir.join(bin_name), pkg)

      # Upload to CIPD.
      if not api.properties.get('tryjob', False):
        UploadPackage(api, bin_name, bin_dir, revision, remote)


def GenTests(api):
  # Tests execution in the event that CIPD doesn't yet have this tool at the
  # specified revision.
  yield (api.test('cipd_is_missing_revision') + api.properties(
      project='infra/infra',
      manifest='infra/infra',
      remote='https://fuchsia.googlesource.com/infra/infra',
      revision='c22471f4e3f842ae18dd9adec82ed9eb78ed1127'
  ) + api.step_data(
      'cipd search fuchsia/infra/catapult/linux-amd64 git_revision:c22471f4e3f842ae18dd9adec82ed9eb78ed1127',
      api.json.output({
          'result': []
      }),
  ))
  # Tests execution in the event that CIPD already has this tool at the
  # specified revision.
  yield (api.test('cipd_has_revision') + api.properties(
      project='infra/infra',
      manifest='infra/infra',
      remote='https://fuchsia.googlesource.com/infra/infra',
      revision='c22471f4e3f842ae18dd9adec82ed9eb78ed1127'
  ) + api.step_data(
      'cipd search fuchsia/infra/catapult/linux-amd64 git_revision:c22471f4e3f842ae18dd9adec82ed9eb78ed1127',
      api.json.output({
          'result':
              ['Packages: go/cmd/github.com/golang/dep/linux-amd64:abc123']
      }),
  ))
  # Tests execution in the event that this is a tryjob.
  yield (api.test('cq_and_cipd_has_revision') + api.properties(
      project='infra/infra',
      manifest='infra/infra',
      tryjob=True,
      remote='https://fuchsia.googlesource.com/infra/infra'))
