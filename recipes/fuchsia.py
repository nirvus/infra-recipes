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
        Property(
            kind=str, help='Revision which triggered this build.',
            default=None),

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
    'patch_issue':
        Property(kind=int, help='Gerrit patch issue number', default=None),
    'patch_project':
        Property(kind=str, help='Gerrit project', default=None),
    'patch_ref':
        Property(kind=str, help='Gerrit patch ref', default=None),
    'patch_repository_url':
        Property(
            kind=str,
            help='Repository which Gerrit change patches',
            default=None),

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

    # Properties pertaining to testing.
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
    # TODO(dbort): Remove upload_archive in favor of archive_gcs_bucket.
    'upload_archive':
        Property(
            kind=bool,
            help='Whether to upload archive of the build artifacts'
            ' (always False if tryjob is True)',
            default=True),
    'archive_gcs_bucket':
        Property(
            kind=str,
            help='The GCS bucket to upload build artifacts to. Will not'
            ' upload a snapshot if this property is blank or if tryjob'
            ' is True.',
            default='fuchsia-archive'),
}


def RunSteps(api, project, manifest, remote, revision, checkout_snapshot,
             repository, patch_gerrit_url, patch_issue, patch_project,
             patch_ref, patch_repository_url, target, build_type, packages,
             variant, gn_args, run_tests, runtests_args, run_host_tests,
             device_type, networking_for_tests, ninja_targets,
             test_timeout_secs, upload_archive, archive_gcs_bucket,
             upload_breakpad_symbols, snapshot_gcs_bucket):
  # Don't upload snapshots for tryjobs.
  if api.properties.get('tryjob'):
    snapshot_gcs_bucket = None
    archive_gcs_bucket = None

  # TODO(dbort): Remove this once upload_archive goes away.
  if not upload_archive:
    archive_gcs_bucket = None

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
    if api.properties.get('tryjob'):
      api.fuchsia.checkout_patched_snapshot(
          patch_gerrit_url=patch_gerrit_url,
          patch_issue=patch_issue,
          patch_project=patch_project,
          patch_ref=patch_ref,
          patch_repository_url=patch_repository_url,
      )
    else:
      api.fuchsia.checkout_snapshot(repository, revision)
  else:
    assert manifest
    assert remote
    api.fuchsia.checkout(
        manifest=manifest,
        remote=remote,
        project=project,
        revision=revision,
        patch_gerrit_url=patch_gerrit_url,
        patch_project=patch_project,
        patch_ref=patch_ref,
        snapshot_gcs_bucket=snapshot_gcs_bucket,
    )

  if project:
    if project.startswith('vendor/'):
      vendor = project[len('vendor/'):]
      args = [
          '--vendor-layer',
          vendor,
          '--namespaces',
          vendor,
      ]
    else:
      args = [
          '--layer',
          project,
      ]
    api.python(
        'verify FIDL namespaces',
        api.path['start_dir'].join('scripts', 'style',
                                   'verify-fidl-libraries.py'),
        args=args)

  test_cmds = None
  if run_tests:
    test_cmds = [
        'runtests -o %s %s' % (
            api.fuchsia.results_dir_on_target,
            runtests_args,
        )
    ]

  # TODO(INTK-292): Delete the following block once json_validator is a
  # prebuilt.
  if project:
    # Add the tool required to validate build packages.
    packages.append('build/packages/json_validator')
    if len(ninja_targets) > 0:
      # If ninja targets are specified, only those targets will be built; in
      # that case, ensure that json_validator is also built.
      ninja_targets.append('tools/json_validator')

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
  if project:
    validator = build.fuchsia_build_dir.join('tools', 'json_validator')
    if project.startswith('vendor/'):
      layer_args = [
          '--vendor-layer',
          project[len('vendor/'):],
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

  if run_host_tests:
    test_results = api.fuchsia.test_on_host(build)
    api.fuchsia.analyze_test_results('test results', test_results)

  # Upload an archive containing build artifacts if the properties say to do so.
  # Note: if we ran tests, this will only execute if the tests passed.
  if archive_gcs_bucket:
    api.fuchsia.upload_build_artifacts(
        build_results=build,
        bucket=archive_gcs_bucket,
        upload_breakpad_symbols=upload_breakpad_symbols)


def _FuchsiaTest(api,
                 name,
                 clear_default_properties=False,
                 tryjob=False,
                 expect_failure=False,
                 properties=None,
                 steps=()):
  """Returns a test case appropriate for yielding from GenTests().

  Provides default property values for the common cases.

  Args:
    api: RecipeTestApi object.
    name: Test name.
    clear_default_properties: If true, does not provide default values.
        However, setting tryjob=True does still add the tryjob-related
        properties.
    tryjob: If true, adds tryjob-related properties.
    expect_failure: If true, the test is expected to fail before
        completion, so certain common steps shouldn't be expected to happen.
    properties: A required dict of properties to override for this test.
    steps: An optional sequence of RecipeTestApi.step_data objects to append to
        the output of this function.

  Returns:
    TestData object.
  """
  # Tests shouldn't try to create their own tryjob environment, in the same way
  # that cr-buildbucket builders shouldn't specify tryjob-related properties.
  if 'tryjob' in properties:
    # TODO(dbort): Maybe check for patch_ properties, too.
    raise ValueError('Test "%s": Do not specify a "tryjob" property; '
                     'use the tryjob arg.' % name)  # pragma: no cover

  if clear_default_properties:
    final_properties = {}
  else:
    final_properties = dict(
        manifest='fuchsia',
        remote='https://fuchsia.googlesource.com/manifest',
        project='topaz',
        target='x64',
        packages=['topaz/packages/default'],
        revision=api.jiri.example_revision,
    )

  if tryjob:
    gerrit_project = (
        properties.get('project', None) or
        final_properties.get('project', 'topaz'))
    final_properties.update(
        dict(
            # api.properties.tryserver will add patch_* properties based on
            # these gerrit_* properties.
            gerrit_url='https://fuchsia-review.googlesource.com',
            gerrit_project=gerrit_project,
            tryjob=True,
        ))

  # Provided properties override the defaults.
  final_properties.update(properties)

  # Add implicit steps.
  extra_steps = []
  if not expect_failure:
    # Don't add these if the test is expected to raise an exception;
    # the recipes engine will complain that these steps aren't consumed.
    run_tests = final_properties.get('run_tests', False)
    run_host_tests = final_properties.get('run_host_tests', False)
    on_device = final_properties.get('device_type', 'QEMU') != 'QEMU'

    if run_tests:
      extra_steps.append(api.fuchsia.task_step_data(device=on_device))
      extra_steps.append(api.fuchsia.test_step_data())
    if run_host_tests:
      extra_steps.append(api.fuchsia.test_step_data(host_results=True))

  # Assemble the return value.
  ret = api.test(name)

  if tryjob:
    ret += api.properties.tryserver(**final_properties)
  else:
    ret += api.properties(**final_properties)

  for s in extra_steps:
    ret += s
  for s in steps:
    # Provided steps override implicit steps.
    ret += s
  return ret


def GenTests(api):
  # Closure that lets callers skip the 'api' arg.
  def FuchsiaTest(*args, **kwargs):
    return _FuchsiaTest(api, *args, **kwargs)

  # Tests using the defaults provided by FuchsiaTest.
  yield FuchsiaTest('default', properties={})
  yield FuchsiaTest('cq', tryjob=True, properties={})

  # Test cases for running tests.
  yield FuchsiaTest('isolated_tests', properties=dict(run_tests=True))
  yield FuchsiaTest(
      'device_tests',
      properties=dict(
          run_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
      ))
  yield FuchsiaTest(
      'host_tests',
      properties=dict(
          ninja_targets=['build/gn:host_tests'],
          run_host_tests=True,
      ))
  yield FuchsiaTest(
      'host_and_device_tests',
      properties=dict(
          run_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
          run_host_tests=True,
      ))

  # Test cases for tests with networking.
  yield FuchsiaTest(
      'isolated_tests_with_networking',
      properties=dict(
          run_tests=True,
          networking_for_tests=True,
      ))
  yield FuchsiaTest(
      'device_tests_with_networking',
      # Networking is only supported for QEMU, so this test should fail.
      expect_failure=True,
      properties=dict(
          run_tests=True,
          networking_for_tests=True,
          device_type='Intel NUC Kit NUC6i3SYK',
      ),
  )
  yield FuchsiaTest(
      'cq_with_networking',
      tryjob=True,
      # Networking is not supported for tryjobs, so this test should fail.
      expect_failure=True,
      properties=dict(
          run_tests=True,
          networking_for_tests=True,
      ),
  )

  # Test non-uploading CI job.
  yield FuchsiaTest(
      'staging',
      properties=dict(
          upload_snapshot=False,
          upload_archive=False,
      ),
  )

  # Test cases for checking out Fuchsia from a snapshot.
  yield FuchsiaTest(
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
  yield FuchsiaTest(
      'cq_checkout_from_snapshot',
      clear_default_properties=True,
      tryjob=True,
      properties=dict(
          checkout_snapshot=True,
          gerrit_project='snapshots',
          target='x64',
          packages=['topaz/packages/default'],
      ),
  )

  # Test the 'vendor/x' case of verifying build packages.
  # The non-vendor case is tested by most other tests.
  yield FuchsiaTest(
      'build-packages-vendor',
      properties=dict(project='vendor/foobar'),
  )

  # Test cases for uploading snapshots.
  yield FuchsiaTest(
      'cq_no_snapshot',
      tryjob=True,
      properties=dict(snapshot_gcs_bucket=None),
  )
  yield FuchsiaTest(
      'ci_no_snapshot',
      properties=dict(snapshot_gcs_bucket=None),
  )

  # Test cases for archiving artifacts.
  yield FuchsiaTest(
      'cq_no_archive',
      tryjob=True,
      properties=dict(archive_gcs_bucket=''),
  )
  yield FuchsiaTest(
      'ci_no_archive',
      properties=dict(archive_gcs_bucket=''),
  )
  yield FuchsiaTest(
      'ci_override_archive',
      properties=dict(archive_gcs_bucket='different-archive-bucket'),
  )

  # Test cases for generating symbol files as part of the build
  yield FuchsiaTest(
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
