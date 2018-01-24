# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building and publishing Go tools

This recipe assumes that Jiri places the tool-to-build under the local path:

  go/src/$tool_root

This can be controlled with the <project> tag in a manifest file like so:

  <project name="foo_project"
           path="go/src/$tool_root"
           ... />
"""

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'infra/cipd',
    'infra/jiri',
    'infra/git',
    'infra/go',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
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
    'tool_root':
        Property(
            kind=str,
            help='The parent directory of the tool relative to $GOPATH/src',
            default=None),
    'build_path':
        Property(kind=str, help='The path to build relative to $tool_root'),
    'test_path':
        Property(kind=str, help='The path to test relative to $tool_root'),
    'package_path':
        Property(kind=str, help='The CIPD package path'),
}

# The tag referencing the golang/dep CIPD package used to install dependencies.
#
# Do not confuse this with the version of https://github.com/golang/dep itself.
# The CIPD package referenced by this version should provide the same version
# of https://github.com/golang/dep that is used for local development
DEP_VERSION = 'version:0.3.2'


def UploadPackage(api, revision, project, remote, package_path, staging_dir):
  """
  Creates and uploads a CIPD package from everything in staging_dir.
  """
  api.cipd.set_service_account_credentials(
      api.cipd.default_bot_service_account_credentials)

  cipd_pkg_name = 'fuchsia/%s/%s' % (package_path, api.cipd.platform_suffix())
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=staging_dir,
  )
  pkg_def.add_file(staging_dir.join(project))

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
             build_path, test_path, tool_root, package_path):
  api.jiri.ensure_jiri()
  api.go.ensure_go()

  # Checkout the project at the specified patch.
  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    revision = api.jiri.project([project]).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  # Install golang/dep for dependencies.
  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
          'go/cmd/github.com/golang/dep/${platform}': DEP_VERSION,
      })

  gopath = api.path['start_dir'].join('go')
  dep_exe = cipd_dir.join('dep')

  # The directory where the project binary will be built.
  staging_dir = api.path.mkdtemp(project)

  with api.context(env={'GOPATH': gopath}):
    absolute_tool_root = api.path['start_dir'].join('go', 'src', *tool_root.split('/'))
    # Download dependencies.
    with api.context(cwd=absolute_tool_root):
      api.step('dep_ensure', [dep_exe, 'ensure'])

    # Build and test.
    with api.context(cwd=staging_dir):
      api.go('build', api.path.join(tool_root, build_path))
      api.go('test', api.path.join(tool_root, test_path))

  # Upload the new binary to CIPD.
  if not api.properties.get('tryjob', False):
    UploadPackage(api, revision, project, remote, package_path, staging_dir)


def GenTests(api):
  # Tests execution in the event that CIPD doesn't yet have this tool at the
  # specified revision.
  yield (api.test('cipd_is_missing_revision') + api.properties(
      project='infra',
      manifest='manifest',
      remote='https://fuchsia.googlesource.com/infra/infra',
      tool_root='fuchsia.googlesource.com/catapult',
      build_path='cmd/catapult',
      test_path='...',
      package_path='infra/catapult') + api.step_data(
          'cipd search fuchsia/infra/catapult/linux-amd64 git_revision:' +
          api.jiri.example_revision,
          api.json.output({
              'result': []
          }),
      ))
  # Tests execution in the event that CIPD already has this tool at the
  # specified revision.
  yield (api.test('cipd_has_revision') + api.properties(
      project='infra',
      manifest='manifest',
      remote='https://fuchsia.googlesource.com/infra/infra',
      tool_root='fuchsia.googlesource.com/catapult',
      build_path='cmd/catapult',
      test_path='...',
      package_path='infra/catapult') + api.step_data(
          'cipd search fuchsia/infra/catapult/linux-amd64 git_revision:' +
          api.jiri.example_revision,
          api.json.output({
              'result':
                  ['Packages: go/cmd/github.com/golang/dep/linux-amd64:abc123']
          }),
      ))
  # Tests execution in the event that this is a tryjob.
  yield (api.test('cq & cipd_has_revision') + api.properties(
      tryjob=True,
      project='infra',
      manifest='manifest',
      remote='https://fuchsia.googlesource.com/infra/infra',
      tool_root='fuchsia.googlesource.com/catapult',
      build_path='cmd/catapult',
      test_path='...',
      package_path='infra/catapult'))
