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

TARGETS = [
    'arm64', 'x64',
    # TODO(dbort): Remove these entries and the mapping in RunSteps once the
    # buildbucket config starts using the new ones.
    'aarch64', 'x86_64',
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
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'upload_snapshot': Property(kind=bool,
                              help='Whether to upload jiri snapshot'
                                   ' (always False if tryjob is True)',
                              default=True),
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url,
             remote, manifest, project, target, upload_snapshot):
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      upload_snapshot=upload_snapshot and not api.properties.get('tryjob'),
  )

  with api.context(infra_steps=True):
    # api.fuchsia.checkout() will have ensured that jiri exists.
    revision = api.jiri.project(['third_party/webkit']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  # TODO(dbort): Remove this mapping and the entries in TARGETS once the
  # buildbucket config starts using the new ones.
  if target == 'aarch64': # pragma: no cover
    target = 'arm64'
  if target == 'x86_64': # pragma: no cover
    target = 'x64'

  build = api.fuchsia.build(
      target=target,
      build_type=BUILD_TYPE,
      packages=['topaz/packages/webkit'],
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
      target='x86_64',
  )
  yield api.test('cq') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x86_64',
      tryjob=True,
  )
