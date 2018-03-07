# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia SDKs."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property, StepFailure

import hashlib


DEPS = [
  'infra/cipd',
  'infra/goma',
  'infra/go',
  'infra/gsutil',
  'infra/hash',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

# Test summary from the core tests, which run directly from userboot.
CORE_TESTS_MATCH = r'CASES: +(\d+) +SUCCESS: +(\d+) +FAILED: +(?P<failed>\d+)'

# Test summary from the runtests command on a booted system.
BOOTED_TESTS_MATCH = r'SUMMARY: Ran (\d+) tests: (?P<failed>\d+) failed'

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                                   default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'use_goma': Property(kind=bool, help='Whether to use goma to compile',
                       default=True),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
}


def BuildZircon(api, project):
  build_zircon_cmd = [
      api.path['start_dir'].join('scripts', 'build-zircon.sh'),
      '-t', project,
  ]
  api.step('build ' + project, build_zircon_cmd)


@contextmanager
def GomaContext(api, use_goma):
  if not use_goma:
    yield
  else:
    with api.goma.build_with_goma():
      yield


def BuildFuchsia(api, release_build, target_cpu, fuchsia_build_dir, packages, use_goma, gn_args):
  with api.step.nest('build fuchsia %s' % target_cpu), GomaContext(api, use_goma):
    gen_cmd = [
        api.path['start_dir'].join('build', 'gn', 'gen.py'),
        '--target_cpu=%s' % target_cpu,
        '--packages=%s' % ','.join(packages),
        '--build-dir=%s' % fuchsia_build_dir,
    ]

    if use_goma:
      gen_cmd.append('--goma=%s' % api.goma.goma_dir)

    if release_build:
      gen_cmd.append('--release')

    for arg in gn_args:
      gen_cmd.append('--args')
      gen_cmd.append(arg)

    api.step('gen', gen_cmd)

    ninja_cmd = [
        api.path['start_dir'].join('buildtools', 'ninja'),
        '-C', fuchsia_build_dir,
    ]

    if use_goma:
      ninja_cmd.extend(['-j', api.goma.recommended_goma_jobs])
    else:
      ninja_cmd.extend(['-j', api.platform.cpu_count])

    api.step('ninja', ninja_cmd)


def MakeSdk(api, outdir, sdk):
  api.go('run',
         api.path['start_dir'].join('scripts', 'makesdk.go'),
         '-out-dir', outdir,
         '-output', sdk,
         api.path['start_dir'])


def PackageArchive(api, sdk):
  return api.hash.sha1(
      'hash archive', sdk, test_data='27a0c185de8bb5dba483993ff1e362bc9e2c7643')


def UploadArchive(api, sdk, digest):
  api.gsutil.upload(
      'fuchsia',
      sdk,
      'sdk/linux-amd64/%s' % digest,
      name='upload fuchsia-sdk %s' % digest,
      unauthenticated_url=True
  )
  snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
  api.jiri.snapshot(snapshot_file)
  api.gsutil.upload('fuchsia-snapshots', snapshot_file, digest,
      link_name='jiri.snapshot',
      name='upload jiri.snapshot',
      unauthenticated_url=True)


def UploadPackage(api, outdir, digest):
  cipd_pkg_name = 'fuchsia/sdk/' + api.cipd.platform_suffix()
  cipd_pkg_file = api.path['tmp_base'].join('sdk.cipd')

  api.cipd.build(
      input_dir=outdir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy',
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'jiri_snapshot': digest,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      '/'.join(['sdk', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']]),
      unauthenticated_url=True
  )


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             use_goma, gn_args):
  api.jiri.ensure_jiri()
  api.go.ensure_go(use_deprecated=True)
  api.gsutil.ensure_gsutil()
  if use_goma:
    api.goma.ensure_goma()

  with api.context(infra_steps=True):
    api.jiri.checkout(manifest, remote, project, patch_ref, patch_gerrit_url)

  build_type = 'release'
  release_build = True

  fuchsia_out_dir = api.path['start_dir'].join('out')

  for target_cpu in ['x64', 'arm64']:
    BuildZircon(api, target_cpu)
    # Build a version with bootfs and a version without so consumers can transition over.
    fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_type, target_cpu))
    packages = ['garnet/packages/sdk']
    BuildFuchsia(api, release_build, target_cpu, fuchsia_build_dir, packages, use_goma, gn_args)
    fuchsia_build_dir_bootfs = fuchsia_out_dir.join('%s-%s-bootfs' % (build_type, target_cpu))
    packages = ['garnet/packages/sdk_bootfs']
    gn_args_bootfs = gn_args + [ 'bootfs_packages=true' ]
    BuildFuchsia(api, release_build, target_cpu, fuchsia_build_dir_bootfs, packages, use_goma,
                 gn_args_bootfs)

  outdir = api.path.mkdtemp('sdk')
  sdk = api.path['tmp_base'].join('fuchsia-sdk.tgz')
  MakeSdk(api, outdir, sdk)

  if not api.properties.get('tryjob', False):
    digest = PackageArchive(api, sdk)
    UploadArchive(api, sdk, digest)
    UploadPackage(api, outdir, digest)


def GenTests(api):
  yield (api.test('ci') +
      api.properties(project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet',
          gn_args=['test']))
  yield (api.test('cq_try') +
      api.properties.tryserver(
          project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet',
          gerrit_project='zircon',
          patch_gerrit_url='fuchsia-review.googlesource.com'))
  yield (api.test('no_goma') +
      api.properties(
          project='garnet',
          manifest='manifest/garnet',
          remote='https://fuchsia.googlesource.com/garnet',
          use_goma=False))
