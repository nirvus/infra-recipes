# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building libffmpeg and uploading it and required source files."""

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/fuchsia',
  'infra/gsutil',
  'infra/jiri',
  'infra/tar',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/step',
]

# Patterns of source code to include in the archive that this recipe produces.
# All relative to third_party/ffmpeg.
SOURCE_PATTERNS = ['fuchsia/config/**/*', 'lib*/*.h', 'LICENSE.md']

TARGETS = ['arm64', 'x64']

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'project': Property(kind=str, help='Jiri remote manifest project',
                      default=None),
  'revision': Property(kind=str, help='Revision of manifest to import', default=None),
  'snapshot_gcs_bucket': Property(kind=str,
                                  help='The GCS bucket to upload a jiri snapshot of the build'
                                       ' to. Will not upload a snapshot if this property is'
                                       ' blank or tryjob is True',
                                  default='fuchsia-snapshots'),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, patch_storage,
             patch_repository_url, revision, project, snapshot_gcs_bucket):
  if api.properties.get('tryjob'):
    snapshot_gcs_bucket = None
  checkout = api.fuchsia.checkout(
      manifest='manifest/ffmpeg',
      remote='https://fuchsia.googlesource.com/third_party/ffmpeg',
      project=project,
      revision=revision,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      snapshot_gcs_bucket=snapshot_gcs_bucket,
  )

  with api.context(infra_steps=True):
    # api.fuchsia.checkout() will have ensured that jiri exists.
    revision = api.jiri.project(['third_party/ffmpeg']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  # Build and archive for all targets before uploading any to avoid an
  # incomplete upload.
  api.tar.ensure_tar()
  archives = {}  # keyed by target string
  for target in TARGETS:
    with api.step.nest('build %s' % target):
      build_results = api.fuchsia.build(
          target=target,
          build_type='release',
          packages=['third_party/ffmpeg/packages/ffmpeg'],
          ninja_targets=['third_party/ffmpeg'],
      )
    with api.context(infra_steps=True):
      with api.step.nest('archive %s' % target):
        # Archive build artifacts and source files.
        archive = api.tar.create(
            api.path['cleanup'].join('%s.tar.gz' % target), compression='gzip')
        archives[target] = archive
        shared_build_dir = build_results.fuchsia_build_dir.join(
            '%s-shared' % target)
        archive.add(shared_build_dir.join('libffmpeg.so'), shared_build_dir)
        ffmpeg_dir = checkout.root_dir.join('third_party', 'ffmpeg')
        source_paths = []
        for pattern in SOURCE_PATTERNS:
          source_paths.extend(api.file.glob_paths(
            name='glob',
            source=ffmpeg_dir,
            pattern=pattern,
            test_data=['third_party/ffmpeg/%s' % pattern.replace('*', 'Star')]))
        for source_path in source_paths:
          archive.add(source_path, directory=ffmpeg_dir)
        archive.tar('tar')

  # If this isn't a real run, don't pollute the storage.
  if api.properties.get('tryjob'):
    return

  # Upload the built library to Google Cloud Storage.
  # api.fuchsia.checkout() doesn't always ensure that gsutil exists.
  api.gsutil.ensure_gsutil()

  with api.context(infra_steps=True):
    for target in TARGETS:
      basename = 'libffmpeg.tar.gz'
      # Use the same arch names that CIPD uses.
      cipd_arch = {'arm64': 'arm64', 'x64': 'amd64'}[target]
      # The GCS path includes the HEAD git revision that was used to build the
      # prebuilt. Since the git repo contains the manifest, and all manifest
      # entries (all the way down) should be pinned, this should exactly
      # describe the environment used to build the artifact.
      gcs_path = api.gsutil.join(
          'lib', 'ffmpeg', 'fuchsia-' + cipd_arch, revision, basename)
      api.gsutil.upload(
          bucket='fuchsia',
          src=archives[target].path,
          dst=gcs_path,
          link_name=basename,
          unauthenticated_url=True,
          name='upload %s' % target,
      )


def GenTests(api):
  yield api.test('default')
  yield api.test('cq') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      tryjob=True,
  )
  yield api.test('cq_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      tryjob=True,
      snapshot_gcs_bucket=None,
  )
  yield api.test('ci_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      snapshot_gcs_bucket=None,
  )
