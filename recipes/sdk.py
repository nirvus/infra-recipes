# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building Fuchsia SDKs."""

from contextlib import contextmanager

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/cipd',
    'infra/fuchsia',
    'infra/go',
    'infra/gsutil',
    'infra/hash',
    'infra/jiri',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
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
}


def RunSteps(api, patch_gerrit_url, patch_project, patch_ref, patch_storage,
             patch_repository_url, project, manifest, remote):
  api.go.ensure_go()

  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      upload_snapshot=False)

  with api.context(infra_steps=True):
    # api.fuchsia.checkout() will have ensured that jiri exists.
    revision = api.jiri.project(['garnet']).json.output[0]['revision']
    api.step.active_result.presentation.properties['got_revision'] = revision

  for target in TARGETS:
    with api.step.nest('build ' + target):
      # For each target, build both bootfs and non-bootfs versions of the
      # system, putting the artifacts from both builds under the same out/.
      # TODO(IN-306): Remove the bootfs path when clients no longer need it.
      with api.step.nest('bootfs'):
        bootfs_build = api.fuchsia.build(
            target=target,
            build_type=BUILD_TYPE,
            packages=['garnet/packages/sdk/bootfs'],
            gn_args=['bootfs_packages=true'])
        # //scripts/makesdk.go expects the bootfs build to live in a directory
        # like "out/release-x64-bootfs".
        bootfs_path = str(bootfs_build.fuchsia_build_dir) + '-bootfs'
        api.file.move('move out dir', bootfs_build.fuchsia_build_dir,
                      bootfs_path)
      with api.step.nest('base'):
        # Build the normal (non-bootfs) system under the same out/.
        bootfs = api.fuchsia.build(
            target=target,
            build_type=BUILD_TYPE,
            packages=['garnet/packages/sdk/base'])

  with api.step.nest('make sdk'):
    outdir = api.path.mkdtemp('sdk')
    sdk = api.path['cleanup'].join('fuchsia-sdk.tgz')
    MakeSdk(api, outdir, sdk)

  if not api.properties.get('tryjob'):
    with api.step.nest('upload sdk'):
      api.gsutil.ensure_gsutil()
      digest = PackageArchive(api, sdk)
      UploadArchive(api, sdk, digest)
      UploadPackage(api, outdir, digest)


def MakeSdk(api, outdir, sdk):
  api.go('run', api.path['start_dir'].join('scripts', 'makesdk.go'), '-out-dir',
         outdir, '-output', sdk, api.path['start_dir'])


def PackageArchive(api, sdk):
  return api.hash.sha1(
      'hash archive', sdk, test_data='27a0c185de8bb5dba483993ff1e362bc9e2c7643')


def UploadArchive(api, sdk, digest):
  archive_base_location = 'sdk/linux-amd64'
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


def UploadPackage(api, outdir, digest):
  cipd_pkg_name = 'fuchsia/sdk/' + api.cipd.platform_suffix()
  cipd_pkg_file = api.path['cleanup'].join('sdk.cipd')

  api.cipd.build(
      input_dir=outdir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy')
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={'jiri_snapshot': digest})

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      '/'.join([
          'sdk',
          api.cipd.platform_suffix(),
          step_result.json.output['result']['instance_id']
      ]),
      unauthenticated_url=True)


# yapf: disable
def GenTests(api):
  yield (api.test('ci') +
      api.properties(
          project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet'))
  yield (api.test('cq_try') +
      api.properties.tryserver(
          project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet',
          patch_gerrit_url='fuchsia-review.googlesource.com',
          tryjob=True))
# yapf: enable
