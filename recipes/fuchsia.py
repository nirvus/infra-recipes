# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Fuchsia and running tests."""

from contextlib import contextmanager

from recipe_engine.config import Enum, List, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


TARGETS = ['arm64', 'x64']

BUILD_TYPES = ['debug', 'release', 'thinlto', 'lto']

DEPS = [
  'infra/fuchsia',
  'infra/gsutil',
  'infra/hash',
  'infra/swarming',
  'infra/tar',
  'recipe_engine/path',
  'recipe_engine/properties',
]

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
  'target': Property(kind=Enum(*TARGETS), help='Target to build'),
  'build_type': Property(kind=Enum(*BUILD_TYPES),
                         help='The build type', default='debug'),
  'packages': Property(kind=List(basestring), help='Packages to build',
                       default=[]),
  # TODO(mknyszek): Rename to 'variants' since this property is a list.
  'variant': Property(kind=List(basestring),
                      help='--variant arguments to gen.py', default=[]),
  'gn_args': Property(kind=List(basestring), help='Extra args to pass to GN',
                      default=[]),
  'run_tests': Property(kind=bool,
                        help='Whether to run tests or not',
                        default=False),
  'runtests_args': Property(kind=str,
                            help='Arguments to pass to the executable running tests',
                            default=''),
  'test_timeout_secs': Property(kind=int,
                                help='How long to wait until timing out on tests',
                                default=40*60),
  'upload_snapshot': Property(kind=bool,
                          help='Whether to upload jiri snapshot'
                               ' (always False if tryjob is True)',
                          default=True),
  'upload_archive': Property(kind=bool,
                          help='Whether to upload archive of the build artifacts'
                               ' (always False if tryjob is True)',
                          default=True),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             target, build_type, packages, variant, gn_args, run_tests, runtests_args,
             test_timeout_secs, upload_snapshot, upload_archive):
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
      upload_snapshot=upload_snapshot and not api.properties.get('tryjob'),
  )
  test_cmds = None
  if run_tests:
    test_cmds = ['runtests -o %s %s' % (
      api.fuchsia.target_test_dir(),
      runtests_args,
    )]
  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      test_cmds=test_cmds,
  )
  if run_tests:
    test_results = api.fuchsia.test(build, timeout_secs=test_timeout_secs)
    api.fuchsia.analyze_test_results('test results', test_results)
  if upload_archive and not api.properties.get('tryjob'):
    api.gsutil.ensure_gsutil()
    api.tar.ensure_tar()

    package = api.tar.create(api.path['tmp_base'].join('fuchsia.tar.gz'), 'gzip')
    package.add(build.fuchsia_build_dir.join('images'), build.fuchsia_build_dir)
    package.tar('tar fuchsia')
    digest = api.hash.sha1('hash archive', package.archive,
                           test_data='cd963da3f17c3acc611a9b9c1b272fcd6ae39909')
    api.gsutil.upload('fuchsia-archive', package.archive, digest,
                      link_name='fuchsia.tar.gz',
                      name='upload fuchsia.tar.gz')


def GenTests(api):
  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.step_data('collect', api.swarming.collect(
      outputs=['output.fs'],
  ))

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
  )
  yield api.test('staging') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      upload_snapshot=False,
      upload_archive=False,
  )
  yield api.test('cq') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      upload_snapshot=True,
      upload_archive=True,
      tryjob=True,
  )
