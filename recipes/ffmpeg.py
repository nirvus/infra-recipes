# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building FFmpeg and uploading it and required source files."""

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property

DEPS = [
    'infra/fuchsia',
    'infra/gsutil',
    'infra/jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/step',
]

REPOSITORY = 'https://fuchsia.googlesource.com/third_party/ffmpeg'

# Patterns of source code to include in the archive that this recipe produces.
# All relative to third_party/ffmpeg.
SOURCE_PATTERNS = ['fuchsia/config/**/*', 'lib*/*.h']

TARGETS = ['arm64', 'x64']

VARIANTS = ['lto', 'thinlto', 'profile', 'asan', 'ubsan']

PROPERTIES = {
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
}


def RunSteps(api, project):
  build_input = api.buildbucket.build.input

  checkout = api.fuchsia.checkout(
      build_input=build_input,
      manifest='manifest/ffmpeg',
      remote=REPOSITORY,
      project=project,
  )

  staging_dir = api.path.mkdtemp('ffmpeg')
  pkg_dir = staging_dir.join('root')

  # Build and archive for all targets before uploading any to avoid an
  # incomplete upload.
  for target in TARGETS:
    with api.step.nest(target):
      ninja_targets = ['%s-shared/libffmpeg.so' % target]
      for variant in VARIANTS:
        ninja_targets.append('%s-%s-shared/libffmpeg.so' % (target, variant))
      build_results = api.fuchsia.build(
          target=target,
          build_type='release',
          packages=['third_party/ffmpeg/packages/ffmpeg'],
          ninja_targets=ninja_targets,
          variants=VARIANTS,
      )
      with api.context(infra_steps=True):
        shared_build_dir = build_results.fuchsia_build_dir.join(
            '%s-shared' % target)
        lib_dir = pkg_dir.join('arch', target, 'lib')
        api.file.ensure_directory('create lib dir', lib_dir)
        api.file.copy('copy libffmpeg.so',
                      shared_build_dir.join('libffmpeg.so'), lib_dir)
        debug_dir = pkg_dir.join('arch', target, 'debug')
        api.file.ensure_directory('create debug dir', debug_dir)
        api.file.copy('copy libffmpeg.so (debug)',
                      shared_build_dir.join('lib.unstripped', 'libffmpeg.so'),
                      debug_dir)

        for variant in VARIANTS:
          with api.step.nest(variant):
            shared_variant_build_dir = build_results.fuchsia_build_dir.join(
                '%s-%s-shared' % (target, variant))
            lib_variant_dir = lib_dir.join(variant)
            api.file.ensure_directory('create lib dir', lib_variant_dir)
            api.file.copy('copy libffmpeg.so',
                          shared_variant_build_dir.join('libffmpeg.so'),
                          lib_variant_dir)
            debug_variant_dir = debug_dir.join(variant)
            api.file.ensure_directory('create debug dir', debug_variant_dir)
            api.file.copy('copy libffmpeg.so (debug)',
                          shared_variant_build_dir.join('lib.unstripped',
                                                        'libffmpeg.so'),
                          debug_variant_dir)

  ffmpeg_dir = checkout.root_dir.join('third_party', 'ffmpeg')
  api.python(
      'copy files',
      api.resource('copy_files.py'),
      args=[
          ffmpeg_dir,
          pkg_dir.join('pkg', 'ffmpeg', 'include'),
      ] + SOURCE_PATTERNS)
  docs_dir = pkg_dir.join('pkg', 'ffmpeg', 'docs')
  api.file.ensure_directory('create docs dir', docs_dir)
  api.file.copy('copy license',
                ffmpeg_dir.join('LICENSE.md'),
                docs_dir.join('LICENSE.md'))

  cipd_pkg_name = 'fuchsia/lib/ffmpeg/fuchsia'
  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name, package_root=pkg_dir, install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/ffmpeg.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('ffmpeg.cipd')
  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )

  if api.properties.get('tryjob'):
    return

  with api.context(infra_steps=True):
    # api.fuchsia.checkout() will have ensured that jiri exists.
    revision = api.jiri.project(
        ['third_party/ffmpeg']).json.output[0]['revision']

  cipd_pins = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if cipd_pins:
    api.step('Package is up-to-date', cmd=None)

  cipd_pin = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'git_repository': REPOSITORY,
          'git_revision': revision,
      },
  )


def GenTests(api):
  yield (api.fuchsia.test(
      'default',
      clear_default_properties=True,
      properties=dict(project='third_party/ffmpeg'),
  ) + api.step_data('cipd search fuchsia/lib/ffmpeg/fuchsia git_revision:' +
                    api.jiri.example_revision,
                    api.cipd.example_search('fuchsia/lib/ffmpeg/fuchsia', [])))
  yield api.fuchsia.test(
      'ci',
      clear_default_properties=True,
      properties=dict(project='third_party/ffmpeg'),
  )
  yield api.fuchsia.test(
      'cq',
      clear_default_properties=True,
      tryjob=True,
      properties=dict(project='third_party/ffmpeg'),
  )
