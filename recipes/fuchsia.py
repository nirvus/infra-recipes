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

DEVICES = ['QEMU', 'Intel NUC Kit NUC6i3SYK']

DEPS = [
    'infra/fuchsia',
    'infra/gsutil',
    'infra/hash',
    'infra/jiri',
    'infra/tar',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/step',
]

PROPERTIES = {
    # Properties for checking out code from a Jiri manifest.
    # NOTE: These properties are ignored if checkout_snapshot is True.
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use', default=None),
    'remote':
        Property(kind=str, help='Remote manifest repository', default=None),
    'revision':
        Property(kind=str, help='Revision which triggered this build.', default=None),

    # Properties for checking out code from a snapshot.
    'checkout_snapshot':
        Property(
            kind=bool,
            help='Whether or not to checkout from a Jiri snapshot.'
                 ' Snapshot is expected to be found at revision in repository.',
            default=False),
    'repository':
        Property(
            kind=str,
            help='Repository which triggered this build.'
                 ' Set by luci-scheduler. Used if checkout_snapshot is True.',
            default=None),

    # Properties for applying a change from Gerrit as a patch.
    # NOTE: in the case of checkout_snapshot, these are treated as applying
    # to the snapshot, and not the full checkout.
    'patch_gerrit_url':
        Property(kind=str, help='Gerrit host', default=None),
    'patch_project':
        Property(kind=str, help='Gerrit project', default=None),
    'patch_ref':
        Property(kind=str, help='Gerrit patch ref', default=None),

    # Properties pertaining to the build.
    'target':
        Property(kind=Enum(*TARGETS), help='Target to build'),
    'build_type':
        Property(
            kind=Enum(*BUILD_TYPES), help='The build type', default='debug'),
    'packages':
        Property(kind=List(basestring), help='Packages to build', default=[]),
    # TODO(mknyszek): Rename to 'variants' since this property is a list.
    'variant':
        Property(
            kind=List(basestring),
            help='--variant arguments to GN in `select_variant`',
            default=[]),
    'gn_args':
        Property(
            kind=List(basestring), help='Extra args to pass to GN', default=[]),
    'ninja_targets': Property(
        kind=List(basestring), help='Extra target args to pass to ninja', default=[]),
    'upload_breakpad_symbols':
        Property(
            kind=bool,
            help='Whether to upload breakpad symbol files',
            default=False),
    # Properties pertaining to testing.
    'run_tests':
        Property(kind=bool, help='Whether to run tests or not', default=False),
    'runtests_args':
        Property(
            kind=str,
            help='Shell-quoted string to add to the runtests commandline',
            default=''),
    'device_type':
        Property(
            kind=Enum(*DEVICES),
            help='The type of device to execute tests on, if the value is'
            ' not QEMU it will be passed to Swarming as the device_type'
            ' dimension',
            default='QEMU'),
    'networking_for_tests':
        Property(
            kind=bool,
            help='Whether tests should have access to the network'
            ' (if True, will cause a failure if tryjob is True or'
            ' if device_type != QEMU)',
            default=False),
    'test_timeout_secs':
        Property(
            kind=int,
            help='How long to wait until timing out on tests',
            default=40 * 60),

    # Properties pertaining to uploading build artifacts.
    'snapshot_gcs_bucket':
        Property(
            kind=str,
            help='The GCS bucket to upload a jiri snapshot of the build'
            ' to. Will not upload a snapshot if this property is'
            ' blank, tryjob is True, or checkout_snapshot is True.',
            default='fuchsia-snapshots'),
    'upload_archive':
        Property(
            kind=bool,
            help='Whether to upload archive of the build artifacts'
            ' (always False if tryjob is True)',
            default=True),
}


def RunSteps(api, project, manifest, remote, revision, checkout_snapshot,
             repository, patch_gerrit_url, patch_project, patch_ref, target,
             build_type, packages, variant, gn_args, run_tests, runtests_args,
             device_type, networking_for_tests, ninja_targets, test_timeout_secs,
             upload_archive, upload_breakpad_symbols, snapshot_gcs_bucket):
  # Don't upload snapshots for tryjobs.
  if api.properties.get('tryjob'):
    snapshot_gcs_bucket = None

  # Handle illegal setting of networking_for_tests.
  if networking_for_tests:
    if device_type != 'QEMU':
      raise api.step.InfraFailure(
          'networking for tests is not yet implemented for non-QEMU tests')
    elif api.properties.get('tryjob'):
      # We must make absolutely sure that networking_for_tests is never set in a
      # tryjob, because a tryjob may be execute unvetted code. Letting that code
      # access the internet can lead to abuse of the CQ system for botnets, among
      # other things.
      raise api.step.InfraFailure(
          'networking for tests is not available for tryjobs')

  if checkout_snapshot:
    assert repository
    assert revision
    api.fuchsia.checkout_snapshot(
        repository=repository,
        revision=revision,
        patch_ref=patch_ref,
        patch_gerrit_url=patch_gerrit_url,
        patch_project=patch_project,
    )
  else:
    assert manifest
    assert remote
    api.fuchsia.checkout(
        manifest=manifest,
        remote=remote,
        project=project,
        revision=revision,
        patch_ref=patch_ref,
        patch_gerrit_url=patch_gerrit_url,
        patch_project=patch_project,
        snapshot_gcs_bucket=snapshot_gcs_bucket,
    )

  test_cmds = None
  if run_tests:
    test_cmds = [
        'runtests -o %s %s' % (
            api.fuchsia.target_test_dir(),
            runtests_args,
        )
    ]
  verify_build_packages = project and (
      project in ['garnet', 'peridot', 'topaz'] or
      project.startswith('vendor/'))
  if verify_build_packages:
    # Add the tool required to validate build packages.
    packages.append('build/packages/json_validator')
  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      ninja_targets=ninja_targets,
      test_cmds=test_cmds,
      test_device_type=device_type,
  )
  if verify_build_packages:
    validator = build.fuchsia_build_dir.join('tools', 'json_validator')
    if project.startswith('vendor/'):
      layer_args = [
          '--vendor-layer',
          project[7:],
      ]
    else:
      layer_args = [
          '--layer',
          project,
      ]
    api.python(
        'verify build packages',
        api.path['start_dir'].join('scripts', 'packages', 'verify_layer.py'),
        args=layer_args + [
            '--json-validator',
            validator,
        ])

  if run_tests:
    test_results = api.fuchsia.test(
        build=build,
        timeout_secs=test_timeout_secs,
        external_network=networking_for_tests,
    )
    api.fuchsia.analyze_test_results('test results', test_results)

  # Upload an archive containing build artifacts if the properties say to do so.
  # Note: if we ran tests, this will only execute if the tests passed.
  if upload_archive and not api.properties.get('tryjob'):
    api.fuchsia.upload_build_artifacts(build, upload_breakpad_symbols=upload_breakpad_symbols)


# yapf: disable
def GenTests(api):
  # Test cases for running Fuchsia tests as a swarming task.
  yield api.test('isolated_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
  ) + api.fuchsia.task_step_data() + api.fuchsia.test_step_data()
  yield api.test('device_tests') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
      device_type='Intel NUC Kit NUC6i3SYK',
  ) + api.fuchsia.task_step_data(device=True) + api.fuchsia.test_step_data()

  # Test cases for tests with networking.
  yield api.test('isolated_tests_with_networking') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
      networking_for_tests=True,
  ) + api.fuchsia.task_step_data() + api.fuchsia.test_step_data()
  yield api.test('device_tests_with_networking') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
      networking_for_tests=True,
      device_type='Intel NUC Kit NUC6i3SYK',
  )
  yield api.test('cq_with_networking') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      run_tests=True,
      networking_for_tests=True,
      tryjob=True,
  )

  # Test cases for skipping Fuchsia tests.
  yield api.test('default') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      revision=api.jiri.example_revision,
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
      upload_archive=True,
      tryjob=True,
  )

  # Test cases for checking out Fuchsia from a snapshot.
  yield api.test('checkout_from_snapshot') + api.properties(
      checkout_snapshot=True,
      repository='https://fuchsia.googlesource.com/snapshots',
      revision='69acf9677ff075e15329cc860d968c1f70be5e6a',
      target='x64',
      packages=['topaz/packages/default'],
  )

  # Test cases for verifying build packages.
  yield api.test('build-packages') + api.properties(
      manifest='manifest/topaz',
      project='topaz',
      remote='https://fuchsia.googlesource.com/topaz',
      target='x64',
      packages=['topaz/packages/default'],
  )
  yield api.test('build-packages-vendor') + api.properties(
      manifest='manifest/foobar',
      project='vendor/foobar',
      remote='https://fuchsia.googlesource.com/foobar',
      target='x64',
      packages=['vendor/foobar/packages/default'],
  )

  # Test cases for uploading snapshots.
  yield api.test('cq_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      snapshot_gcs_bucket=None,
      tryjob=True,
  )
  yield api.test('ci_no_snapshot') + api.properties.tryserver(
      patch_project='fuchsia',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      target='x64',
      packages=['topaz/packages/default'],
      snapshot_gcs_bucket=None,
  )

  # Test cases for generating symbol files as part of the build
  yield api.test('upload_breakpad_symbols') + api.properties(
      manifest='fuchsia',
      remote='https://fuchsia.googlesource.com/manifest',
      # build_type and target determine the path used in the key of
      # fuchsia.breakpad_symbol_summary below.
      build_type='release',
      target='x64',
      packages=['topaz/packages/default'],
      revision=api.jiri.example_revision,
      upload_archive=True,
      upload_breakpad_symbols=True,
      tryjob=False,
      ninja_targets=['build/gn:breakpad_symbols']
  ) + api.fuchsia.breakpad_symbol_summary({'/path/to/bin': '[START_DIR]/out/release-x64/bin.sym'})

# yapf: enable
