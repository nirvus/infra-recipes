# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia SDKs."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property, StepFailure


DEPS = [
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
  'use_goma': Property(kind=bool, help='Whether to use goma to compile',
                       default=True),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
}


def BuildMagenta(api, target):
  build_magenta_cmd = [
      api.path['start_dir'].join('scripts', 'build-magenta.sh'),
      '-c',
      '-t', target,
  ]
  api.step('build magenta', build_magenta_cmd)


@contextmanager
def GomaContext(api, use_goma):
  if not use_goma:
    yield
  else:
    with api.goma.build_with_goma():
      yield


def BuildFuchsia(api, release_build, gn_target, fuchsia_build_dir,
                 modules, use_goma, gn_args):
  with api.step.nest('build fuchsia'), GomaContext(api, use_goma):
    gen_cmd = [
        api.path['start_dir'].join('packages', 'gn', 'gen.py'),
        '--target_cpu=%s' % gn_target,
        '--modules=%s' % ','.join(modules),
        '--ignore-skia'
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


def MakeSdk(api, sdk):
  api.go('run',
         api.path['start_dir'].join('scripts', 'makesdk.go'),
         '-output', sdk,
         api.path['start_dir'])


def UploadArchive(api, sdk):
    digest = api.hash.sha1(
        'hash archive', sdk, test_data='27a0c185de8bb5dba483993ff1e362bc9e2c7643')
    dest = 'sdk/linux-amd64/%s' % digest
    api.gsutil.upload('fuchsia',
                      sdk,
                      dest,
                      name='upload fuchsia-sdk',
                      unauthenticated_url=True)
    snapshot_file = api.path['tmp_base'].join('jiri.snapshot')
    step_result = api.jiri.snapshot(api.raw_io.output(leak_to=snapshot_file))
    api.gsutil.upload('fuchsia', snapshot_file, 'sdk/snapshots/' + digest,
                      link_name='jiri.snapshot',
                      name='upload jiri.snapshot',
                      unauthenticated_url=True)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, use_goma, gn_args):
  api.jiri.ensure_jiri()
  api.go.ensure_go()
  api.gsutil.ensure_gsutil()
  if use_goma:
    api.goma.ensure_goma()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(
        'fuchsia', 'https://fuchsia.googlesource.com/manifest')
    api.jiri.clean(all=True)
    api.jiri.update(gc=True)

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url, rebase=True)

  modules = ['sdk']
  build_type = 'release'
  release_build = True
  target = 'x86_64'
  gn_target = 'x86-64'

  fuchsia_out_dir = api.path['start_dir'].join('out')
  fuchsia_build_dir = fuchsia_out_dir.join('%s-%s' % (build_type, gn_target))

  BuildMagenta(api, target)
  BuildFuchsia(api, release_build, gn_target,
               fuchsia_build_dir, modules, use_goma, gn_args)

  sdk = api.path.mkdtemp('sdk').join('fuchsia-sdk.tgz')
  MakeSdk(api, sdk)

  if not api.properties.get('tryjob', False):
    UploadArchive(api, sdk)


def GenTests(api):
  yield (api.test('ci') +
         api.properties(gn_args=['test']))
  yield (api.test('cq_try') +
         api.properties.tryserver(
         gerrit_project='magenta',
         patch_gerrit_url='fuchsia-review.googlesource.com'))
  yield (api.test('no_goma') +
         api.properties(use_goma=False))
