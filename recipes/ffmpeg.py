# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building libffmpeg.so."""

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/fuchsia',
  'infra/gsutil',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/properties',
  'recipe_engine/step',
]

BUILD_TYPE = 'release'

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'project': Property(kind=str, help='Jiri remote manifest project',
                      default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'snapshot_gcs_bucket': Property(kind=str,
                                  help='The GCS bucket to upload a jiri snapshot of the build'
                                       ' to. Will not upload a snapshot if this property is'
                                       ' blank or tryjob is True',
                                  default='fuchsia-snapshots'),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url,
             remote, manifest, project, snapshot_gcs_bucket):
  if api.properties.get('tryjob'):
    snapshot_gcs_bucket = None
  checkout = api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      snapshot_gcs_bucket=snapshot_gcs_bucket,
  )

  with api.context(infra_steps=True):
    # api.fuchsia.checkout() will have ensured that jiri exists.
    revision = api.jiri.project(['third_party/ffmpeg']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  for target in ['arm64', 'x64']:
    build = api.fuchsia.build(
        target=target,
        build_type=BUILD_TYPE,
        packages=['garnet/packages/prod/ffmpeg'],
        ninja_targets=['third_party/ffmpeg'],
    )

    # Upload the built library to Google Cloud Storage.
    if not api.properties.get('tryjob'):
      # api.fuchsia.checkout() doesn't always ensure that gsutil exists.
      api.gsutil.ensure_gsutil()

      # The GCS path has three main components:
      # - target architecture
      # - third_party/ffmpeg git HEAD hash
      # - garnet jiri.snapshot file hash
      # The HEAD hash component lets us find all builds for a given version
      # of the ffmpeg code. But, since the actual binary includes pieces
      # of garnet (header-defined values, static libs, etc.), it's also
      # important to reflect the garnet version.
      bucket_root = {'arm64': 'aarch64', 'x64': 'x86_64'}[target]
      api.gsutil.upload(
          bucket='fuchsia',
          src=build.fuchsia_build_dir.join('%s-shared' % target, 'libffmpeg.so'),
          dst=api.gsutil.join(bucket_root, 'ffmpeg', revision,
                              checkout.snapshot_file_sha1, 'libffmpeg.so'),
          link_name='libffmpeg.so',
          unauthenticated_url=True,
          name='upload libffmpeg.so',
      )


def GenTests(api):
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
  )
  yield api.test('cq') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      tryjob=True,
  )
  yield api.test('cq_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      tryjob=True,
      snapshot_gcs_bucket=None,
  )
  yield api.test('ci_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      snapshot_gcs_bucket=None,
  )
