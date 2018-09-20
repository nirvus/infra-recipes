# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building Fuchsia SDKs."""

from contextlib import contextmanager

from recipe_engine.config import Enum
from recipe_engine.recipe_api import Property

import collections

DEPS = [
    'infra/bazel',
    'infra/cipd',
    'infra/fuchsia',
    'infra/go',
    'infra/gsutil',
    'infra/hash',
    'infra/jiri',
    'infra/tar',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/step',
]

PROJECTS = ['garnet', 'topaz']

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
        Property(kind=Enum(*PROJECTS), help='Jiri remote manifest project'),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
    'revision':
        Property(kind=str, help='Revision of manifest to import', default=None),
}

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
      revision = api.jiri.project([project]).json.output[0]['revision']
      api.step.active_result.presentation.properties['got_revision'] = revision

  # Build fuchsia for each target.
  builds = {}
  for target in ('arm64', 'x64'):
    with api.step.nest('build ' + target):
      sdk_build_package = '%s/packages/sdk/%s' % (project, project)
      builds[target] = api.fuchsia.build(
          target=target,
          build_type=BUILD_TYPE,
          packages=[sdk_build_package],
          gn_args=['build_sdk_archives=true'])

  # Merge the SDK archives for each target into a single archive.
  # Note that "alpha" and "beta" below have no particular meaning.
  merge_path = api.path['start_dir'].join('scripts', 'sdk', 'merger',
                                          'merge.py')
  full_archive_path = api.path['cleanup'].join('merged_sdk_archive.tar.gz')
  api.python('merge sdk archives',
      merge_path,
      args=[
        '--alpha-archive',
        builds['x64'].fuchsia_build_dir.join('sdk', 'archive', '%s.tar.gz' %
                                             project),
        '--beta-archive',
        builds['arm64'].fuchsia_build_dir.join('sdk', 'archive', '%s.tar.gz' %
                                               project),
        '--output-archive',
        full_archive_path,
      ])

  if project == 'topaz':
    scripts_path = api.path['start_dir'].join('scripts', 'sdk', 'bazel')
    sdk_dir = api.path['cleanup'].join('sdk-bazel')

    api.python('create bazel sdk',
        scripts_path.join('generate.py'),
        args=[
          '--archive',
          full_archive_path,
          '--output',
          sdk_dir,
        ],
    )

    with api.step.nest('test sdk'):
      test_workspace_dir = api.path['cleanup'].join('tests')
      api.python('create test workspace',
          scripts_path.join('generate-tests.py'),
          args=[
            '--sdk',
            sdk_dir,
            '--output',
            test_workspace_dir,
          ],
      )

      bazel_path = api.bazel.ensure_bazel()

      api.python('run tests',
          test_workspace_dir.join('run.py'),
          args=[
            '--bazel',
            bazel_path,
          ],
      )

    if not api.properties.get('tryjob'):
      with api.step.nest('upload bazel sdk'):
        # Upload the SDK to CIPD and GCS.
        UploadPackage(api, 'bazel', sdk_dir, remote, revision)

  # Likewise for the Chromium SDK, but by other legacy means.
  elif project == 'garnet':
    sdk_dir = api.path['cleanup'].join('chromium-sdk')

    # Extract the archive to a directory for CIPD processing.
    with api.step.nest('extract chromium sdk'):
      api.file.ensure_directory('create sdk dir', sdk_dir)
      api.tar.ensure_tar()
      api.tar.extract(
          step_name='unpack sdk archive',
          path=full_archive_path,
          directory=sdk_dir,
      )

    if not api.properties.get('tryjob'):
      with api.step.nest('upload chromium sdk'):
        # Upload the Chromium style SDK to GCS and CIPD.
        UploadArchive(api, full_archive_path, sdk_dir, remote, revision)

# Given an SDK |sdk_name| with artifacts found in |staging_dir|, upload a
# corresponding .cipd file to CIPD and GCS.
def UploadPackage(api, sdk_name, staging_dir, remote, revision):
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
        'git_repository': remote,
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


def UploadArchive(api, sdk, out_dir, remote, revision):
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
        'git_repository': remote,
        'git_revision': revision,
        'jiri_snapshot': digest,
      }
  )


# yapf: disable
def GenTests(api):
  yield (api.test('ci_garnet') +
      api.properties(
          project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet',
          revision=api.jiri.example_revision) +
      api.step_data('upload chromium sdk.hash archive',
                    api.hash('27a0c185de8bb5dba483993ff1e362bc9e2c7643')))
  yield (api.test('ci_topaz') +
      api.properties(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz',
          revision=api.jiri.example_revision))
  yield (api.test('ci_new_garnet') +
      api.properties(
          project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet') +
      api.step_data('upload chromium sdk.cipd search fuchsia/sdk/chromium/linux-amd64 ' +
                    'git_revision:' + api.jiri.example_revision,
                     api.json.output({'result': []})) +
      api.step_data('upload chromium sdk.hash archive',
                    api.hash('27a0c185de8bb5dba483993ff1e362bc9e2c7643')))
  yield (api.test('ci_new_topaz') +
      api.properties(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz') +
      api.step_data('upload bazel sdk.cipd search fuchsia/sdk/bazel/linux-amd64 ' +
                    'git_revision:' + api.jiri.example_revision,
                     api.json.output({'result': []})))
  yield (api.test('cq_try') +
      api.properties(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz') +
      api.properties.tryserver(
          project='topaz',
          manifest='manifest/topaz',
          remote='https://fuchsia.googlesource.com/topaz',
          patch_gerrit_url='fuchsia-review.googlesource.com',
          tryjob=True))
# yapf: enable
