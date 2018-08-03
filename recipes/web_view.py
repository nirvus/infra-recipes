# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building libwebkit.so."""

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

TARGETS = ['arm64', 'x64']

PROPERTIES = {
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'revision': Property(kind=str, help='Revision', default=None),
  'snapshot_gcs_bucket': Property(kind=str,
                                  help='The GCS bucket to upload a jiri snapshot of the build'
                                       ' to. Will not upload a snapshot if this property is'
                                       ' blank or tryjob is True',
                                  default='fuchsia-snapshots'),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, patch_storage,
             patch_repository_url, revision, snapshot_gcs_bucket):
  if api.properties.get('tryjob'):
    snapshot_gcs_bucket = None
  checkout = api.fuchsia.checkout(
      manifest='manifest/webkit',
      remote='https://fuchsia.googlesource.com/third_party/webkit',
      project='third_party/webkit',
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      revision=revision,
      snapshot_gcs_bucket=snapshot_gcs_bucket,
  )

  with api.context(infra_steps=True):
    # api.fuchsia.checkout() will have ensured that jiri exists.
    revision = api.jiri.project(['third_party/webkit']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  # Build for all targets before uploading any to avoid an incomplete upload.
  builds = {}  # keyed by target string
  for target in TARGETS:
    with api.step.nest('build ' + target):
      builds[target] = api.fuchsia.build(
          target=target,
          build_type='release',
          packages=['third_party/webkit/packages/webkit'],
          ninja_targets=['third_party/webkit'],
      )

  # If this isn't a real run, don't pollute the storage.
  if api.properties.get('tryjob'):
    return

  # Upload the built library to Google Cloud Storage.
  # api.fuchsia.checkout() doesn't always ensure that gsutil exists.
  api.gsutil.ensure_gsutil()

  for target in TARGETS:
    with api.step.nest('upload ' + target):
      # The GCS path has three main components:
      # - target architecture
      # - third_party/webkit git HEAD hash
      # - topaz jiri.snapshot file hash
      # The HEAD hash component lets us find all builds for a given version
      # of the webkit code. But, since the actual binary includes pieces
      # of topaz (header-defined values, static libs, etc.), it's also
      # important to reflect the topaz version.
      bucket_root = {'arm64': 'aarch64', 'x64': 'x86_64'}[target]
      build_dir = builds[target].fuchsia_build_dir
      api.gsutil.upload(
          bucket='fuchsia',
          src=build_dir.join('%s-shared' % target, 'libwebkit.so'),
          dst=api.gsutil.join(bucket_root, 'webkit', revision,
                              checkout.snapshot_file_sha1, 'libwebkit.so'),
          link_name='libwebkit.so',
          unauthenticated_url=True,
          name='upload libwebkit.so',
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
