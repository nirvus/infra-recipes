# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building Fuchsia SDKs."""

from contextlib import contextmanager

from recipe_engine.recipe_api import Property

import collections

DEPS = [
    'infra/cipd',
    'infra/fuchsia',
    'infra/go',
    'infra/gsutil',
    'infra/hash',
    'infra/jiri',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/step',
]

TARGETS = ('arm64', 'x64')

BUILD_TYPE = 'release'

PROPERTIES = {
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
    'revision':
        Property(kind=str, help='Revision of manifest to import', default=None),
}

# namedtuple representing an SDK type to be built and uploaded to CIPD and GCS.
# |name| is the name of the SDK
# |script_path| is the path from the fuchsia root at which one finds the
#   script that generates the SDK artifacts.
SDKType = collections.namedtuple('SDKType', ('name', 'script_path'))

# The current list of SDKTypes that we build for.
SDK_TYPES = (
    SDKType(
        name='fuchsia',
        script_path=('scripts', 'sdk', 'foundation', 'generate.py'),
    ),
    SDKType(
        name='bazel',
        script_path=('scripts', 'sdk', 'bazel', 'generate.py'),
    ),
)

def RunSteps(api, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             revision):
  api.go.ensure_go()
  api.gsutil.ensure_gsutil()

  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      revision=revision,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project)

  with api.context(infra_steps=True):
    if not revision:
      # api.fuchsia.checkout() will have ensured that jiri exists.
      revision = api.jiri.project(['topaz']).json.output[0]['revision']
      api.step.active_result.presentation.properties['got_revision'] = revision

  # Build fuchsia for each target.
  builds = {}
  for target in TARGETS:
    with api.step.nest('build ' + target):
      builds[target] = api.fuchsia.build(
          target=target,
          build_type=BUILD_TYPE,
          packages=['topaz/packages/sdk/topaz'])

  # For each SDK type, per target, invoke the corresponding script that creates
  # the layout of artifacts and upload these to CIPD and GCS.
  for sdk_type in SDK_TYPES:
    script_path = api.path['start_dir'].join(*sdk_type.script_path)
    sdk_dir = api.path['cleanup'].join('sdk-%s' % sdk_type.name)

    # If |overlay| is false, the --output directory is deleted before producing
    # the SDK; if true, the script verifies that the --output directory exists
    # before overlaying content in it.
    overlay = False
    for target in TARGETS:
        api.python('create %s sdk' % sdk_type.name,
            script_path,
            args=[
              '--manifest',
              builds[target].fuchsia_build_dir.join('sdk-manifests', 'topaz'),
              '--output',
              sdk_dir,
            ] + (['--overlay'] if overlay else []),
        )
        overlay = True

    if not api.properties.get('tryjob'):
      with api.step.nest('upload %s sdk' % sdk_type.name):
        # Upload the SDK to CIPD and GCS.
        UploadPackage(api, sdk_type.name, sdk_dir, revision)

  # Likewise for the Chromium SDK, but by other legacy means.
  with api.step.nest('make chromium sdk'):
    out_dir = api.path['cleanup'].join('chromium-sdk')
    sdk = api.path['cleanup'].join('chromium-sdk.tgz')
    api.go('run', api.path['start_dir'].join('scripts', 'sdk', 'foundation', 'makesdk.go'),
           '-out-dir', out_dir, '-output', sdk, api.path['start_dir'])

  if not api.properties.get('tryjob'):
    with api.step.nest('upload chromium sdk'):
      # Upload the Chromium style SDK to GCS and CIPD.
      UploadArchive(api, sdk, out_dir, revision)

# Given an SDK |sdk_name| with artifacts found in |staging_dir|, upload a
# corresponding .cipd file to CIPD and GCS.
def UploadPackage(api, sdk_name, staging_dir, revision):
  if sdk_name == 'fuchsia':
    sdk_subpath = 'sdk/%s' % api.cipd.platform_suffix()
  else:
    sdk_subpath = 'sdk/%s/%s' % (sdk_name,  api.cipd.platform_suffix())

  cipd_pkg_name = 'fuchsia/%s' % sdk_subpath
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=staging_dir,
      install_mode='copy')
  pkg_def.add_dir(staging_dir)
  pkg_def.add_version_file('.versions/sdk.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('sdk.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'git_repository': 'https://fuchsia.googlesource.com/topaz',
        'git_revision': revision,
      }
  )

  instance_id = step_result.json.output['result']['instance_id']
  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join(sdk_subpath, instance_id),
      unauthenticated_url=True
  )


def UploadArchive(api, sdk, out_dir, revision):
  digest = api.hash.sha1('hash archive', sdk)
  archive_base_location = 'sdk/' + api.cipd.platform_suffix()
  archive_bucket = 'fuchsia'
  api.gsutil.upload(
      bucket=archive_bucket,
      src=sdk,
      dst='%s/%s' % (archive_base_location, digest),
      link_name='archive',
      name='upload fuchsia-sdk %s' % digest,
      unauthenticated_url=True)
  # Note that this will upload the snapshot to a location different from the
  # path that api.fuchsia copied it to. This uses a path based on the hash of
  # the SDK artifact, not based on the hash of the snapshot itself. Clients can
  # use this to find the snapshot used to build a specific SDK artifact.
  snapshot_file = api.path['cleanup'].join('jiri.snapshot')
  api.jiri.snapshot(snapshot_file)
  api.gsutil.upload(
      bucket='fuchsia-snapshots',
      src=snapshot_file,
      dst=digest,
      link_name='jiri.snapshot',
      name='upload jiri.snapshot',
      unauthenticated_url=True)
  # Record the digest of the most recently uploaded archive for downstream autorollers.
  digest_path = api.path['cleanup'].join('digest')
  api.file.write_text('write digest', digest_path, digest)
  api.gsutil.upload(
      bucket=archive_bucket,
      src=digest_path,
      dst='%s/LATEST_ARCHIVE' % archive_base_location,
      link_name='LATEST_ARCHIVE',
      name='upload latest digest',
      unauthenticated_url=True)

  # Upload the SDK to CIPD as well.
  cipd_pkg_name = 'fuchsia/sdk/chromium/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=out_dir,
      install_mode='copy')
  pkg_def.add_dir(out_dir)

  api.cipd.create_from_pkg(
      pkg_def=pkg_def,
      refs=['latest'],
      tags={
        'git_repository': 'https://fuchsia.googlesource.com/topaz',
        'git_revision': revision,
        'jiri_snapshot': digest,
      }
  )


# yapf: disable
def GenTests(api):
  yield (api.test('ci') +
      api.properties(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz',
          revision=api.jiri.example_revision) +
      api.step_data('upload chromium sdk.hash archive',
                    api.hash('27a0c185de8bb5dba483993ff1e362bc9e2c7643')))
  yield (api.test('ci_new') +
      api.properties(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz') +
      api.step_data('upload fuchsia sdk.cipd search fuchsia/sdk/linux-amd64 ' +
                    'git_revision:' + api.jiri.example_revision,
                     api.json.output({'result': []})) +
      api.step_data('upload bazel sdk.cipd search fuchsia/sdk/bazel/linux-amd64 ' +
                    'git_revision:' + api.jiri.example_revision,
                     api.json.output({'result': []})) +
      api.step_data('upload chromium sdk.cipd search fuchsia/sdk/chromium/linux-amd64 ' +
                    'git_revision:' + api.jiri.example_revision,
                     api.json.output({'result': []})) +
      api.step_data('upload chromium sdk.hash archive',
                    api.hash('27a0c185de8bb5dba483993ff1e362bc9e2c7643')))
  yield (api.test('cq_try') +
      api.properties.tryserver(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz',
          patch_gerrit_url='fuchsia-review.googlesource.com',
          tryjob=True))
# yapf: enable
