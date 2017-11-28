# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building WebView."""

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/goma',
  'infra/gsutil',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/step',
]

TARGETS = ['aarch64', 'x86_64']

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
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote, target):
  api.jiri.ensure_jiri()
  api.gsutil.ensure_gsutil()
  api.goma.ensure_goma()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url,
                      patch_project)
    revision = api.jiri.project(['third_party/webkit']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  zircon_project = {
    'aarch64': 'zircon-qemu-arm64',
    'x86_64': 'zircon-pc-x86-64',
  }[target]
  build_zircon_cmd = [
    api.path['start_dir'].join('scripts/build-zircon.sh'),
    '-c',
    '-p', zircon_project,
  ]
  api.step('build zircon', build_zircon_cmd)

  gen_target = {'aarch64': 'aarch64', 'x86_64': 'x86-64'}[target]
  fuchsia_build_dir = api.path['start_dir'].join('out', 'release-%s' % gen_target)

  with api.step.nest('build fuchsia'), api.goma.build_with_goma():
    api.step('gen', [
      api.path['start_dir'].join('build/gn/gen.py'),
      '--target_cpu=%s' % gen_target,
      '--packages=topaz/packages/webkit',
      '--args', 'use_prebuilt_webkit=false',
      '--goma=%s' % api.goma.goma_dir,
      '--release',
    ])
    api.step('ninja', [
      api.path['start_dir'].join('buildtools/ninja'),
      '-C', fuchsia_build_dir,
      '-j', api.goma.recommended_goma_jobs,
      'topaz/runtime/web_view:webkit',
    ])

  gn_target = {'aarch64': 'arm64', 'x86_64': 'x64'}[target]

  api.gsutil.upload('fuchsia',
      fuchsia_build_dir.join('%s-shared' % gn_target, 'libwebkit.so'),
      api.gsutil.join(target, 'webkit', revision, 'libwebkit.so'),
      link_name='libwebkit.so',
      name='upload libwebkit.so',
      unauthenticated_url=True)


def GenTests(api):
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86_64',
  )
