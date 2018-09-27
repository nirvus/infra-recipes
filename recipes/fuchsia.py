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

DEVICES = [
    'QEMU', 'Intel NUC Kit NUC6i3SYK', 'Intel NUC Kit NUC7i5DNHE', 'HiKey 960'
]

DEPS = [
    'infra/cipd',
    'infra/fuchsia',
    'infra/gsutil',
    'infra/hash',
    'infra/jiri',
    'infra/tar',
    'infra/testsharder',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
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

    # Properties for checking out code from a snapshot.
    'checkout_snapshot':
        Property(
            kind=bool,
            help='Whether or not to checkout from a Jiri snapshot.'
            ' Snapshot is expected to be found at revision in repository.',
            default=False),

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
    'ninja_targets':
        Property(
            kind=List(basestring),
            help='Extra target args to pass to ninja',
            default=[]),
    'upload_breakpad_symbols':
        Property(
            kind=bool,
            help='Whether to upload breakpad symbol files',
            default=False),
    'boards':
        Property(kind=List(basestring), help='Boards to build', default=[]),
    'products':
        Property(kind=List(basestring), help='Products to build', default=[]),
    'zircon_args':
        Property(
            kind=List(basestring),
            help=
            'Additional args to pass to zircon build using standard FOO=bar syntax.',
            default=[]),

    # Properties pertaining to testing.
    'test_pool':
        Property(
            kind=str,
            help='Swarming pool from which a test task will be drawn',
            default='fuchsia.tests'),
    'run_tests':
        Property(kind=bool, help='Whether to run target tests', default=False),
    'runtests_args':
        Property(
            kind=str,
            help='Shell-quoted string to add to the runtests commandline',
            default=''),
    'run_host_tests':
        Property(kind=bool, help='Whether to run host tests', default=False),
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
    'pave':
        Property(
            kind=bool,
            help='Whether to pave images the device for testing. (Ignored if'
            ' device_type == QEMU)',
            default=True),
    'test_timeout_secs':
        Property(
            kind=int,
            help='How long to wait until timing out on tests',
            default=40 * 60),
    'requires_secrets':
        Property(
            kind=bool,
            help='Whether any plaintext needs to be supplied to the tests',
            default=False),
    'test_in_shards':
        Property(
            kind=bool,
            help='Whether to run tests as shards',
            default=False),

    # Properties pertaining to uploading build artifacts.
    'snapshot_gcs_bucket':
        Property(
            kind=str,
            help='The GCS bucket to upload a jiri snapshot of the build'
            ' to. Will not upload a snapshot if this property is'
            ' blank, tryjob is True, or checkout_snapshot is True.',
            default='fuchsia-snapshots'),
    'archive_gcs_bucket':
        Property(
            kind=str,
            help='The GCS bucket to upload build artifacts to. Will not'
            ' upload a snapshot if this property is blank or if tryjob'
            ' is True.',
            default='fuchsia-archive')
}


def RunSteps(api, project, manifest, remote, checkout_snapshot, target,
             build_type, packages, variant, gn_args, test_pool, run_tests,
             runtests_args, run_host_tests, device_type, networking_for_tests,
             pave, ninja_targets, test_timeout_secs, requires_secrets,
             test_in_shards, archive_gcs_bucket, upload_breakpad_symbols,
             snapshot_gcs_bucket, boards, products, zircon_args):
  tryjob = api.properties.get('tryjob')

  # Don't upload snapshots for tryjobs.
  if tryjob:
    snapshot_gcs_bucket = None
    archive_gcs_bucket = None

  # Handle illegal setting of networking_for_tests.
  if networking_for_tests:
    # We must make absolutely sure that networking_for_tests is never set in a
    # tryjob, because a tryjob may execute unvetted code. Letting that code
    # access the internet can lead to abuse of the CQ system for botnets, among
    # other things.
    if tryjob or device_type != 'QEMU':
      raise api.step.InfraFailure(
          'networking for tests is not available for tryjobs and '
          'is not yet implemented for non-QEMU tests')

  # Handle illegal settings around secrets.
  if requires_secrets:
    if tryjob or not networking_for_tests or device_type != 'QEMU':
      raise api.step.InfraFailure(
          'the secrets pipeline is only supported in tryjobs, ' +
          'when networking for tests enabled, and ' + 'and on QEMU')

  build_input = api.buildbucket.build.input
  if api.properties.get('tryjob'):
    assert len(build_input.gerrit_changes) == 1

  if checkout_snapshot:
    if api.properties.get('tryjob'):
      api.fuchsia.checkout_patched_snapshot(
          gerrit_change=build_input.gerrit_changes[0],)
    else:
      api.fuchsia.checkout_snapshot(gitiles_commit=build_input.gitiles_commit,)
  else:
    assert manifest
    assert remote
    # If we're uploading a snapshot, also upload it to the archive bucket.
    # People downloading a build's artifacts may want to see the corresponding
    # snapshot.
    buckets = ()
    if snapshot_gcs_bucket:
        buckets = (snapshot_gcs_bucket, archive_gcs_bucket)
    api.fuchsia.checkout(
        build_input=build_input,
        manifest=manifest,
        remote=remote,
        project=project,
        snapshot_gcs_buckets=buckets,
    )

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      json_validator_dir = api.path['start_dir'].join('tools', 'json_validator')
      api.cipd.ensure(json_validator_dir, {
          'fuchsia/tools/json_validator/${platform}': 'latest',
      })

  validator = json_validator_dir.join('json_validator')

  if project:
    if project.startswith('vendor/'):
      vendor = project[len('vendor/'):]
      layer_args = [
          '--vendor-layer',
          vendor,
      ]
      namespace_args = [
          '--namespaces',
          vendor,
      ]
    else:
      layer_args = [
          '--layer',
          project,
      ]
      namespace_args = []

    api.python(
        'verify FIDL namespaces',
        api.path['start_dir'].join('scripts', 'style',
                                   'verify-fidl-libraries.py'),
        args=layer_args + namespace_args)

    api.python(
        'verify build packages',
        api.path['start_dir'].join('scripts', 'packages', 'verify_layer.py'),
        args=layer_args + [
            '--json-validator',
            validator,
        ])

  build = api.fuchsia.build(
      target=target,
      build_type=build_type,
      packages=packages,
      variants=variant,
      gn_args=gn_args,
      ninja_targets=ninja_targets,
      boards=boards,
      products=products,
      zircon_args=zircon_args,
  )

  if run_tests:
    if test_in_shards:
      all_results = api.fuchsia.test_in_shards(
          test_pool=test_pool,
          build=build,
          timeout_secs=test_timeout_secs,
      )
    else:
      all_results = [api.fuchsia.test(
          build=build,
          test_pool=test_pool,
          timeout_secs=test_timeout_secs,
          pave=pave,
          test_cmds=[
              'runtests -o %s %s' % (
                  api.fuchsia.results_dir_on_target,
                  runtests_args,
              ),
          ],
          device_type=device_type,
          external_network=networking_for_tests,
          requires_secrets=requires_secrets,
      )]
    for test_results in all_results:
      api.fuchsia.analyze_test_results(test_results)
  else:
    # Bloaty is run during the testing phase for performance reasons, but we
    # also want to run it on build-only bots if specified.
    api.fuchsia.run_bloaty(build)

  if run_host_tests:
    test_results = api.fuchsia.test_on_host(build)
    api.fuchsia.analyze_test_results(test_results)

  # Upload an archive containing build artifacts if the properties say to do so.
  # Note: if we ran tests, this will only execute if the tests passed.
  if archive_gcs_bucket:
    api.fuchsia.upload_build_artifacts(
        build_results=build,
        bucket=archive_gcs_bucket,
        upload_breakpad_symbols=upload_breakpad_symbols)


def GenTests(api):
  # Tests using the defaults provided by fuchsia.test().
  yield api.fuchsia.test('default', properties={})
  yield api.fuchsia.test('cq', tryjob=True, properties={})

  # Test cases for running tests.
  yield api.fuchsia.test('isolated_tests', properties=dict(run_tests=True))
  yield api.fuchsia.test(
      'device_tests',
      properties=dict(
          run_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
      ))
  yield api.fuchsia.test(
      'host_tests',
      properties=dict(
          ninja_targets=['build/gn:host_tests'],
          run_host_tests=True,
      ))
  yield api.fuchsia.test(
      'host_and_device_tests',
      properties=dict(
          run_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
          run_host_tests=True,
      ))

  # Test cases for tests with networking.
  yield api.fuchsia.test(
      'isolated_tests_with_networking',
      properties=dict(
          run_tests=True,
          networking_for_tests=True,
      ))
  yield api.fuchsia.test(
      'device_tests_with_networking',
      # Networking is only supported for QEMU, so this test should fail.
      expect_failure=True,
      clear_default_steps=True,
      properties=dict(
          run_tests=True,
          networking_for_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
      ),
  )
  yield api.fuchsia.test(
      'cq_with_networking',
      tryjob=True,
      # Networking is not supported for tryjobs, so this test should fail.
      expect_failure=True,
      clear_default_steps=True,
      properties=dict(
          run_tests=True,
          networking_for_tests=True,
      ),
  )

  # Test cases for checking out Fuchsia from a snapshot.
  yield api.fuchsia.test(
      'checkout_from_snapshot',
      clear_default_properties=True,
      properties=dict(
          checkout_snapshot=True,
          repository='https://fuchsia.googlesource.com/snapshots',
          revision='69acf9677ff075e15329cc860d968c1f70be5e6a',
          target='x64',
          packages=['topaz/packages/default'],
      ),
  )
  yield api.fuchsia.test(
      'cq_checkout_from_snapshot',
      clear_default_properties=True,
      tryjob=True,
      properties=dict(
          checkout_snapshot=True,
          target='x64',
          packages=['topaz/packages/default'],
      ),
  )

  # Test the 'vendor/x' case of verifying build packages.
  # The non-vendor case is tested by most other tests.
  yield api.fuchsia.test(
      'build-packages-vendor',
      properties=dict(project='vendor/foobar'),
  )

  # Test cases for uploading snapshots.
  yield api.fuchsia.test(
      'cq_no_snapshot',
      tryjob=True,
      properties=dict(snapshot_gcs_bucket=None),
  )
  yield api.fuchsia.test(
      'ci_no_snapshot',
      properties=dict(snapshot_gcs_bucket=None),
  )

  # Test cases for archiving artifacts.
  yield api.fuchsia.test(
      'cq_no_archive',
      tryjob=True,
      properties=dict(archive_gcs_bucket=''),
  )
  yield api.fuchsia.test(
      'ci_no_archive',
      properties=dict(archive_gcs_bucket=''),
  )
  yield api.fuchsia.test(
      'ci_override_archive',
      properties=dict(archive_gcs_bucket='different-archive-bucket'),
  )

  # Test non-uploading CI job.
  yield api.fuchsia.test(
      'ci_no_snapshot_or_archive',
      properties=dict(
          snapshot_gcs_bucket='',
          archive_gcs_bucket='',
      ),
  )

  # Test cases for generating symbol files as part of the build
  yield api.fuchsia.test(
      'upload_breakpad_symbols',
      properties=dict(
          # build_type and target determine the path used in the key of
          # fuchsia.breakpad_symbol_summary below.
          build_type='release',
          target='x64',
          upload_breakpad_symbols=True,
          ninja_targets=['build/gn:breakpad_symbols']),
      steps=[
          api.fuchsia.breakpad_symbol_summary({
              '/path/to/bin': '[START_DIR]/out/release-x64/bin.sym'
          })
      ])

  # Test cases for exercising the secrets pipeline.
  yield api.fuchsia.test(
      'ci_requires_secrets',
      tryjob=False,
      properties=dict(
          requires_secrets=True,
          networking_for_tests=True,
          run_tests=True,
          device_type='QEMU',
      ),
  )
  yield api.fuchsia.test(
      'cq_requires_secrets',
      tryjob=True,
      # Secrets are not supported for tryjobs.
      expect_failure=True,
      clear_default_steps=True,
      properties=dict(
          requires_secrets=True,
          networking_for_tests=True,
          run_tests=True,
          device_type='QEMU',
      ),
  )
  yield api.fuchsia.test(
      'ci_requires_secrets_no_networking',
      tryjob=False,
      # Secrets are not supported without networking.
      expect_failure=True,
      clear_default_steps=True,
      properties=dict(
          requires_secrets=True,
          networking_for_tests=False,
          run_tests=True,
          device_type='QEMU',
      ),
  )
  yield api.fuchsia.test(
      'ci_requires_secrets_on_hardware',
      tryjob=False,
      # Secrets are not supported on hardware.
      expect_failure=True,
      clear_default_steps=True,
      properties=dict(
          requires_secrets=True,
          networking_for_tests=True,
          run_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
      ),
  )

  # Test cases for testing in shards.
  yield api.fuchsia.test(
      'test_in_shards',
      clear_default_steps=True,
      properties=dict(
          run_tests=True,
          test_in_shards=True,
      ),
      steps=[
          api.fuchsia.images_step_data(),
          api.fuchsia.shards_step_data(shards=[
              api.testsharder.shard(
                  name='fuchsia-0000',
                  tests=[api.testsharder.test(
                      name='test0',
                      location='/path/to/test0',
                  )],
                  device_type='QEMU',
              ),
              api.testsharder.shard(
                  name='fuchsia-0001',
                  tests=[api.testsharder.test(
                      name='test1',
                      location='/path/to/test1',
                  )],
                  device_type='NUC',
              ),
          ]),
          api.fuchsia.tasks_step_data(
              api.fuchsia.task_mock_data(id='610', name='fuchsia-0000'),
              api.fuchsia.task_mock_data(id='710', name='fuchsia-0001'),
          ),
          api.fuchsia.test_step_data(shard_name='fuchsia-0000'),
          api.fuchsia.test_step_data(shard_name='fuchsia-0001'),
      ])
