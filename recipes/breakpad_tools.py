# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building some Breakpad tools."""

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property

DEPS = [
    'infra/cipd',
    'infra/git',
    'infra/gitiles',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

BREAKPAD_GIT = 'https://chromium.googlesource.com/breakpad/breakpad'
DEPOT_TOOLS_GIT = 'https://chromium.googlesource.com/chromium/tools/depot_tools.git'

PLATFORMS = ('linux', 'mac')

PROPERTIES = {
    'url':
        Property(kind=str, help='Git repository URL', default=BREAKPAD_GIT),
    'ref':
        Property(kind=str, help='Git reference', default='refs/heads/master'),
    'revision':
        Property(kind=str, help='Revision', default=None),
    'cipd_target':
        Property(
            kind=str,
            help='CIPD target to build (e.g. linux-amd64)',
            default=None),
}


def RunSteps(api, url, ref, revision, cipd_target):
  api.gitiles.ensure_gitiles()

  if not cipd_target:
    # Compute the CIPD target for the host platform if not set.
    cipd_target = '%s-%s' % (api.platform.name, {
        'intel': {
            32: '386',
            64: 'amd64',
        },
        'arm': {
            32: 'armv6',
            64: 'arm64',
        },
    }[api.platform.arch][api.platform.bits])

  cipd_os, _ = cipd_target.split('-')

  if not revision:
    revision = api.gitiles.refs(url).get(ref, None)
  cipd_pkg_name = 'fuchsia/tools/breakpad/' + cipd_target
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  depot_tools_path = api.path['start_dir'].join('depot_tools')
  with api.context(infra_steps=True):
    api.git.checkout(DEPOT_TOOLS_GIT, depot_tools_path)

  # Use gclient to fetch the DEPS.
  breakpad_dir = api.path['start_dir'].join('breakpad')
  api.file.ensure_directory('makedirs breakpad', breakpad_dir)
  with api.context(
      infra_steps=True,
      cwd=breakpad_dir,
      env_prefixes={
          'PATH': [depot_tools_path]
      }):
    api.step('gclient config', [
        'gclient',
        'config',
        '--unmanaged',
        '-v',
        url,
    ])
    api.step('pin git', ['git', '-C', 'src', 'checkout', revision])
    api.step('gclient sync', [
        'gclient',
        'sync',
        '-v',
        '--output-json',
        api.json.output(),
    ])
    api.step.active_result.presentation.properties['got_revision'] = revision

  with api.context(cwd=breakpad_dir.join('src')):
    api.step('configure', ['./configure'])
    api.step('build', [
        'make', 'src/tools/' + cipd_os + '/dump_syms/dump_syms',
        'src/tools/' + cipd_os + '/symupload/sym_upload'
    ])

  build_dir = breakpad_dir.join('src', 'src', 'tools', cipd_os)
  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name, package_root=build_dir, install_mode='copy')
  pkg_def.add_file(build_dir.join('dump_syms', 'dump_syms'))
  pkg_def.add_file(build_dir.join('symupload', 'sym_upload'))
  pkg_def.add_version_file('.versions/breakpad-tools.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('breakpad-tools.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'git_repository': url,
          'git_revision': revision,
      },
  )


def GenTests(api):
  revision = '9eac2058b70615519b2c4d8c6bdbfca1bd079e39'
  yield (
      api.test('default') + api.gitiles.refs('refs',
                                             ('refs/heads/master', revision)))
  for platform in PLATFORMS:
    yield (api.test(platform) + api.platform.name(platform) +
           api.properties(cipd_target=platform + '-amd64') +
           api.gitiles.refs('refs', ('refs/heads/master', revision)))
    yield (api.test(platform + '_new') + api.platform.name(platform) +
           api.properties(cipd_target=platform + '-amd64') + api.gitiles.refs(
               'refs', ('refs/heads/master', revision)) + api.step_data(
                   'cipd search fuchsia/tools/breakpad/' + platform + '-amd64 '
                   + 'git_revision:' + revision, api.json.output({
                       'result': []
                   })))
