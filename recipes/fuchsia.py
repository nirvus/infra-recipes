# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia."""

import re

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/goma',
  'infra/jiri',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

TARGETS = ['arm64', 'x86-64']

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
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'build_variant': Property(kind=Enum('incremental', 'full'),
                            help='The build variant', default='full'),
  'build_type': Property(kind=Enum('debug', 'release'), help='The build type',
                         default='debug'),
  'modules': Property(kind=List(basestring), help='Packages to build',
                      default=[])
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target,
             build_variant, build_type, modules):
  api.goma.ensure_goma()
  api.jiri.ensure_jiri()

  if build_variant == 'incremental':
    checkout = api.path['cache'].join('fuchsia')
  else:
    checkout = api.path['start_dir']

  with api.step.context({'cwd': checkout}):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, overwrite=True)
    api.jiri.clean_project(branches=True)
    api.jiri.update(gc=True)
    if patch_ref is not None:
      api.jiri.patch(patch_ref, host=patch_gerrit_url)
    step_result = api.jiri.snapshot(api.raw_io.output())
    snapshot = step_result.raw_io.output
    step_result.presentation.logs['jiri.snapshot'] = snapshot.splitlines()

  sysroot_target = {'arm64': 'aarch64', 'x86-64': 'x86_64'}[target]

  release_build = (build_type == 'release')
  build_dir_prefix = 'release-%s' if release_build else 'debug-%s'

  # Step: build sysroot
  build_sysroot_cmd_params = [
    checkout.join('scripts', 'build-sysroot.sh'), '-c', '-t', sysroot_target
  ]
  if release_build:
    build_sysroot_cmd_params.append('-r')
  api.step('build sysroot', build_sysroot_cmd_params)

  fuchsia_target = {'arm64': 'aarch64', 'x86-64': 'x86-64'}[target]

  # Step: build Fuchsia
  with api.step.nest('build Fuchsia'), api.goma.build_with_goma():
    gen_cmd_params = [
      checkout.join('packages', 'gn', 'gen.py'),
      '--target_cpu=%s' % fuchsia_target,
      '--goma=%s' % api.goma.goma_dir
    ]
    if release_build:
      gen_cmd_params.append('--release')
    if modules:
      gen_cmd_params.append('--modules=%s' % ','.join(modules))

    api.step('gen', gen_cmd_params)
    api.step(
        'ninja',
        [
          checkout.join('buildtools', 'ninja'),
          '-C', checkout.join('out', build_dir_prefix % fuchsia_target),
          '-j', api.goma.recommended_goma_jobs,
        ]
    )


def GenTests(api):
  for build_variant in ['incremental', 'full']:
    for build_type in ['debug', 'release']:
      yield (api.test('ci_%s_%s' % (build_variant, build_type)) +
             api.properties(manifest='fuchsia',
                            remote='https://fuchsia.googlesource.com/manifest',
                            target='x86-64',
                            build_variant=build_variant,
                            build_type=build_type))
      yield (api.test('ci_modules_%s_%s' % (build_variant, build_type)) +
             api.properties(manifest='fuchsia',
                            remote='https://fuchsia.googlesource.com/manifest',
                            target='x86-64',
                            build_variant=build_variant,
                            build_type=build_type,
                            modules=['foo', 'bar']))
  yield (api.test('cq') +
         api.properties.tryserver(
             gerrit_project='manifest',
             patch_gerrit_url='fuchsia-review.googlesource.com',
             manifest='fuchsia',
             remote='https://fuchsia.googlesource.com/manifest',
             target='x86-64'))
