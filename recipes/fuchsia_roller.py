# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for rolling Fuchsia layers into upper layers."""


from recipe_engine.config import Enum, Single
from recipe_engine.recipe_api import Property

# ROLL_TYPES lists the types of rolls we can perform on the target manifest.
# * 'import': An <import> tag will be updated.
# * 'project': A <project> tag will be updated.
ROLL_TYPES = ['import', 'project']

DEPS = [
  'infra/auto_roller',
  'infra/gitiles',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/step',
]


PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'project': Property(kind=str, help='Jiri remote manifest project', default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'roll_type': Property(kind=Enum(*ROLL_TYPES),
      help='The type of roll to perform', default='import'),
  # TODO(kjharland): Rename to 'manifest_to_edit' since "import" is misleading
  # if we are not actually rolling an <import> tag in the manifest.
  'import_in': Property(kind=str,
      help='Path to the manifest to edit relative to $project'),
  # TODO(kjharland): Rename to 'element_name' because "import" is misleading.
  'import_from': Property(kind=str,
      help='Name of the <project> or <import> to edit in $import_in'),
  # TODO(kjharland): This defaults to fuchsia.googlesource.com/$import_from
  # below to support existing rollers. Do not rely on this behavior as it is
  # going away and explicitly specify the target URL. Delete this property
  # altogether when https://fuchsia.atlassian.net/browse/IN-321 is resolved.
  'roll_from_repo': Property(
    kind=str,
    help='The repo to roll from. Must match the value of the remote= attribute of the $import_from element',
    default=None),
  'revision': Property(kind=str, help='Revision'),
  'dry_run': Property(kind=bool,
                      default=False,
                      help='Whether to dry-run the auto-roller (CQ+1 and abandon the change)'),
}


FUCHSIA_URL = 'https://fuchsia.googlesource.com/'

COMMIT_MESSAGE = """[roll] Roll {project} {old}..{new} ({count} commits)

{commits}
"""


# This recipe has two 'modes' of operation: production and dry-run. Which mode
# of execution should be used is dictated by the 'dry_run' property.
#
# The purpose of dry-run mode is to test the auto-roller end-to-end. This is
# useful because now we can have an auto-roller in staging, and we can block
# updates behind 'dry_run' as a sort of feature gate. It is passed to
# api.auto_roller.attempt_roll() which handles committing changes.
def RunSteps(api, category, project, manifest, remote, roll_type, import_in, import_from,
             roll_from_repo, revision, dry_run):
  api.jiri.ensure_jiri()
  api.gitiles.ensure_gitiles()

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(manifest, remote, project)
    api.jiri.update(run_hooks=False)

    project_dir = api.path['start_dir'].join(*project.split('/'))
    with api.context(cwd=project_dir):
      # Determine whether to update manifest imports or projects.
      if roll_type == 'import':
        updated_section = 'imports'
        imports = [(import_from, revision)]
        projects = None
      elif roll_type == 'project':
        updated_section = 'projects'
        imports = None
        projects = [(import_from, revision)]

      changes = api.jiri.edit_manifest(import_in, projects=projects, imports=imports)

      if len(changes[updated_section]) == 0:
        api.step.active_result.presentation.step_text = 'manifest up-to-date, nothing to roll'
        return
      old_rev = changes[updated_section][0]['old_revision']
      new_rev = changes[updated_section][0]['new_revision']

      # If repository URL was not given for the rolled dependency, assume it
      # lives at fuchsia.googlesource.com.
      # TODO(kjharland): Delete this after making roll_from_repo a required property.
      if not roll_from_repo:
        roll_from_repo = FUCHSIA_URL + import_from

      # Get the commit history and generate a commit message.
      log = api.gitiles.log(roll_from_repo, '%s..%s' % (old_rev, new_rev), step_name='log')
      message = COMMIT_MESSAGE.format(
          project=import_from,
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

    # Land the changes.
    api.auto_roller.attempt_roll(
        gerrit_project=project,
        repo_dir=project_dir,
        commit_message=message,
        dry_run=dry_run,
    )


def GenTests(api):
  # Mock step data intended to be substituted as the result of the first check
  # during polling. It indicates a success, and should end polling.
  success_step_data = api.step_data('check if done (0)', api.auto_roller.success())

  # Test rolling a project instead of an import.
  yield (api.test('cobalt_project') +
        api.properties(project='garnet',
                       manifest='manifest/minimal',
                       remote='https://fuchsia.googlesource.com/garnet',
                       import_in='manifest/third_party',
                       roll_type='project',
                       import_from='cobalt',
                       roll_from_repo='https://cobalt-analytics.googlesource.com/config',
                       revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                       poll_interval_secs=0.001,
                       poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + success_step_data)

  # Test a successful roll of zircon into garnet.
  yield (api.test('zircon') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + success_step_data)

  # Test a no-op roll of zircon into garnet.
  yield (api.test('zircon-noop') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.step_data('jiri edit', api.json.output({'imports':[]})))

  # Test a successful roll of garnet into peridot.
  yield (api.test('garnet') +
         api.properties(project='peridot',
                        manifest='manifest/minimal',
                        import_in='manifest/peridot',
                        import_from='garnet',
                        remote='https://fuchsia.googlesource.com/peridot',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + success_step_data)

  # Test a successful roll of peridot into topaz.
  yield (api.test('peridot') +
         api.properties(project='topaz',
                        manifest='manifest/minimal',
                        import_in='manifest/topaz',
                        import_from='peridot',
                        remote='https://fuchsia.googlesource.com/topaz',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') + success_step_data)

  # Test a dry-run of the auto-roller for rolling zircon into garnet. We
  # substitute in mock data for the first check that the CQ dry-run completed by
  # unsetting the CQ label to indicate that the CQ dry-run finished.
  yield (api.test('zircon_dry_run') +
         api.properties(project='garnet',
                        manifest='manifest/minimal',
                        import_in='manifest/garnet',
                        import_from='zircon',
                        remote='https://fuchsia.googlesource.com/garnet',
                        revision='fc4dc762688d2263b254208f444f5c0a4b91bc07',
                        dry_run=True,
                        poll_interval_secs=0.001,
                        poll_timeout_secs=0.1) +
         api.gitiles.log('log', 'A') +
         api.step_data('check if done (0)', api.auto_roller.dry_run()))
