# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for automatically updating Flutter, flutter/engine, and Dart."""

from collections import OrderedDict
import re

from recipe_engine.config import Enum, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/auto_roller',
  'infra/git',
  'infra/gitiles',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]


PROPERTIES = {
    'revision':
        Property(kind=str, help='flutter/flutter revision'),
}


FLUTTER_NAME = 'external/github.com/flutter/flutter'
ENGINE_NAME = 'external/github.com/flutter/engine'
DART_SDK_NAME = 'dart/sdk'

COMMIT_SUBJECT = """\
[roll] Update {deps}

{logs}

Test: CQ
"""

LOG_FORMAT = """\
{project} {old}..{new} ({count} commits)
{commits}
"""


def UpdateManifestProject(api, manifest, project_name, revision):
  """Updates the revision for a project in a manifest.

  Args:
    api (RecipeApi): Recipe API object.
    manifest (Path): Path to the Jiri manifest to update.
    project_name (str): Name of the project in the Jiri manifest to update.
    revision (str): SHA-1 hash representing the updated revision for
      project_name in the manifest.

  Returns:
    A formatted log string summarizing the updates as well as the project's
    remote property.
  """
  remote = api.jiri.read_manifest_element(
      manifest=manifest,
      element_type='project',
      element_name=project_name,
  ).get('remote')
  changes = api.jiri.edit_manifest(
      manifest=manifest,
      projects=[(project_name, revision)],
      test_data={
          'projects': [{'old_revision': 'abc123', 'new_revision': 'def456'}],
      },
      name='jiri edit %s' % project_name,
  )
  if len(changes['projects']) == 0:
    api.step.active_result.presentation.step_text = 'manifest up-to-date, nothing to roll'
    return None, None
  old_rev = changes['projects'][0]['old_revision']
  new_rev = changes['projects'][0]['new_revision']
  log = api.gitiles.log(remote, '%s..%s' % (old_rev, new_rev), step_name='log %s' % project_name)
  formatted_log = LOG_FORMAT.format(
      project=project_name,
      old=old_rev[:7],
      new=new_rev[:7],
      count=len(log),
      commits='\n'.join([
          '{commit} {subject}'.format(
              commit=commit['id'][:7],
              subject=commit['message'].splitlines()[0],
          ) for commit in log
      ]),
  )
  return formatted_log, remote


def ExtractDartVersionFromDEPS(api, deps_path):
  """Extracts the dart_version from a flutter/engine's DEPS file.

  Args:
    api (RecipeApi): Recipe API object.
    deps_path (Path): A path to the DEPS file for dart third party
      dependencies.
    manifest_path (Path): A path to the Jiri manifest to overwrite.
  """
  contents = api.file.read_text(
      name='read DEPS file',
      source=deps_path,
      test_data='\'dart_revision\': \'abcdeabcdeabcdeabcdeabcdeabcdeabcdeabcde\'',
  )
  m = re.search('\'dart_revision\':\s*\'(?P<revision>[0-9a-f]{40})\'', contents)
  if not m:
    raise api.step.InfraFailure('failed to find dart_revision in DEPS')
  return m.group('revision')


def UpdatePkgManifest(api, dart_path, manifest_path):
  """Overwrites a dart third party package manifest.

  Args:
    api (RecipeApi): Recipe API object.
    dart_path (Path): A path to the dart/sdk repository.
    manifest_path (Path): A path to the Jiri manifest to overwrite.
  """
  api.python(
      name='update %s' % api.path.basename(manifest_path),
      script=dart_path.join('tools', 'create_pkg_manifest.py'),
      args=['-d', dart_path.join('DEPS'),
            '-o', manifest_path],
  )


def RollChanges(api, path, updated_deps):
  """Rolls manifest changes in a git repository.

  Args:
    path (Path): Path to the git repository containing the changes to roll.
    updated_deps (dict[str]str): A map of dependencies that were updated to
    a log string, summarizing the update.
  """
  # Generate the commit message.
  commit_message = COMMIT_SUBJECT.format(
      deps=', '.join(updated_deps.keys()),
      logs='\n'.join(updated_deps.itervalues()))

  # Land the changes.
  api.auto_roller.attempt_roll(
      gerrit_project='topaz',
      repo_dir=api.path['start_dir'].join('topaz'),
      commit_message=commit_message,
  )


def RunSteps(api, revision):
  api.gitiles.ensure_gitiles()
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    # Check out Topaz with minimal dependencies.
    api.jiri.init()
    api.jiri.import_manifest(
        manifest='manifest/minimal',
        remote='https://fuchsia.googlesource.com/topaz',
        name='topaz',
    )
    api.jiri.update(run_hooks=False)

    manifest_repo = api.path['start_dir'].join('topaz')
    flutter_manifest = manifest_repo.join('manifest', 'flutter')
    dart_manifest = manifest_repo.join('manifest', 'dart')

    updated_deps = OrderedDict()

    # Set up a temporary sandbox directory to do the required manipulations to
    # roll flutter, flutter engine, and dart.
    with api.tempfile.temp_dir('sandbox-flutter-dart') as sandbox_dir:
      # Attempt to update the manifest with a new flutter revision.
      flutter_log, flutter_remote = UpdateManifestProject(
          api=api,
          manifest=flutter_manifest,
          project_name=FLUTTER_NAME,
          revision=revision,
      )
      if not flutter_log:
        return
      updated_deps[FLUTTER_NAME] = flutter_log

      # Get the flutter/flutter dependency on flutter/engine.
      flutter_path = sandbox_dir.join('flutter')
      api.git.checkout(
          url=flutter_remote,
          path=flutter_path,
          ref=revision,
      )
      engine_revision = api.file.read_text(
          name='read flutter engine version',
          source=flutter_path.join('bin', 'internal', 'engine.version'),
          test_data='xyz000',
      ).strip()

      # Attempt to update the manifest with a new engine revision.
      engine_log, engine_remote = UpdateManifestProject(
          api=api,
          manifest=flutter_manifest,
          project_name=ENGINE_NAME,
          revision=engine_revision,
      )
      if not engine_log:
        RollChanges(api, manifest_repo, updated_deps)
        return
      updated_deps[ENGINE_NAME] = engine_log

      # Get the flutter/engine dependency on Dart.
      engine_path = sandbox_dir.join('engine')
      api.git.checkout(
          url=engine_remote,
          path=engine_path,
          ref=engine_revision,
      )
      dart_revision = ExtractDartVersionFromDEPS(api, engine_path.join('DEPS'))

      dart_log, dart_remote = UpdateManifestProject(
          api=api,
          manifest=dart_manifest,
          project_name=DART_SDK_NAME,
          revision=dart_revision,
      )
      if not dart_log:
        RollChanges(api, manifest_repo, updated_deps)
        return
      updated_deps[DART_SDK_NAME] = dart_log

      # Get dart/sdk.
      dart_path = sandbox_dir.join('dart')
      api.git.checkout(
          url=dart_remote,
          path=dart_path,
          ref=dart_revision,
      )

      # Update the package manifests.
      UpdatePkgManifest(api,
        dart_path=dart_path,
        manifest_path=manifest_repo.join('manifest', 'dart_third_party_pkg'),
      )
      UpdatePkgManifest(api,
        dart_path=dart_path,
        manifest_path=manifest_repo.join('manifest', 'dart_third_party_pkg_head'),
      )

    # Land the changes.
    RollChanges(api, manifest_repo, updated_deps)


def GenTests(api):
  noop_edit = lambda name: api.step_data(name, api.json.output({'projects': []}))

  flutter_check_data = api.jiri.read_manifest_element(
      api=api,
      manifest='manifest/flutter',
      element_name=FLUTTER_NAME,
      element_type='project',
      test_output={
        'remote': 'https://fuchsia.googlesource.com/third_party/flutter',
      })
  flutter_log_data = api.gitiles.log('log %s' % FLUTTER_NAME, 'A')

  engine_check_data = api.jiri.read_manifest_element(
      api=api,
      manifest='manifest/flutter',
      element_name=ENGINE_NAME,
      element_type='project',
      test_output={
        'remote': 'https://fuchsia.googlesource.com/third_party/flutter',
      })
  engine_log_data = api.gitiles.log('log %s' % ENGINE_NAME, 'A')

  dart_sdk_check_data = api.jiri.read_manifest_element(
      api=api,
      manifest='manifest/dart',
      element_name=DART_SDK_NAME,
      element_type='project',
      test_output={
        'remote': 'https://fuchsia.googlesource.com/third_party/dart',
      })
  dart_sdk_log_data = api.gitiles.log('log %s' % DART_SDK_NAME, 'A')

  yield (api.test('noop roll') +
         api.properties(revision='abc123') +
         flutter_check_data +
         noop_edit('jiri edit %s' % FLUTTER_NAME))

  yield (api.test('flutter/flutter only') +
         api.properties(revision='abc123') +
         flutter_check_data + flutter_log_data +
         engine_check_data +
         noop_edit('jiri edit %s' % ENGINE_NAME) +
         api.step_data('check if done (0)', api.auto_roller.success()))

  yield (api.test('flutter/flutter and flutter/engine') +
         api.properties(revision='abc123') +
         flutter_check_data + flutter_log_data +
         engine_check_data + engine_log_data +
         dart_sdk_check_data +
         noop_edit('jiri edit %s' % DART_SDK_NAME) +
         api.step_data('check if done (0)', api.auto_roller.success()))

  yield (api.test('cannot find dart version') +
         api.properties(revision='abc123') +
         flutter_check_data + flutter_log_data +
         engine_check_data + engine_log_data +
         api.step_data('read DEPS file', api.raw_io.output_text('stuff')))

  yield (api.test('flutter/flutter, flutter/engine, and dart') +
         api.properties(revision='abc123') +
         flutter_check_data + flutter_log_data +
         engine_check_data + engine_log_data +
         dart_sdk_check_data + dart_sdk_log_data +
         api.step_data('check if done (0)', api.auto_roller.success()))
