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
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  # TODO(mknyszek): Remove this property as it is unused.
  'upload_snapshot': Property(kind=bool,
                              help='Whether to upload jiri snapshot'
                                   ' (always False if tryjob is True)',
                              default=True),
  'snapshot_gcs_bucket': Property(kind=str,
                                  help='The GCS bucket to upload a jiri snapshot of the build'
                                       ' to. Will not upload a snapshot if this property is'
                                       ' blank or tryjob is True',
                                  default='fuchsia-snapshots'),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url,
             remote, manifest, project, target, upload_snapshot,
             snapshot_gcs_bucket):
  # TODO(mknyszek): Update this once nothing is using upload_snapshot.
  if api.properties.get('tryjob') or not upload_snapshot:
    snapshot_gcs_bucket = None
  api.fuchsia.checkout(
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
    revision = api.jiri.project(['third_party/webkit']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  build = api.fuchsia.build(
      target=target,
      build_type=BUILD_TYPE,
      packages=['topaz/packages/prod/webkit'],
      gn_args=['use_prebuilt_webkit=false'],
      ninja_targets=['topaz/runtime/web_view:webkit'],
  )

  # Upload the built library to Google Cloud Storage.
  if not api.properties.get('tryjob'):
    # api.fuchsia.checkout() doesn't always ensure that gsutil exists.
    api.gsutil.ensure_gsutil()

    # The GCS path uses old-style target names.
    bucket_root = {'arm64': 'aarch64', 'x64': 'x86_64'}[target]
    api.gsutil.upload(
        bucket='fuchsia',
        src=build.fuchsia_build_dir.join('%s-shared' % target, 'libwebkit.so'),
        dst=api.gsutil.join(bucket_root, 'webkit', revision, 'libwebkit.so'),
        link_name='libwebkit.so',
        unauthenticated_url=True,
        name='upload libwebkit.so',
    )


def GenTests(api):
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
  )
  yield api.test('cq') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      tryjob=True,
  )
  yield api.test('cq_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      tryjob=True,
      snapshot_gcs_bucket=None,
      upload_snapshot=False,
  )
  yield api.test('ci_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      snapshot_gcs_bucket=None,
      upload_snapshot=False,
  )
  # TODO(mknyszek): Delete this test once nothing is using upload_snapshot.
  yield api.test('ci_no_snapshot_deprecated') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      upload_snapshot=False,
  )
  # TODO(mknyszek): Delete this test once nothing is using upload_snapshot.
  yield api.test('cq_no_snapshot_deprecated') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      tryjob=True,
      upload_snapshot=False,
  )
