# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for generating docs."""

from contextlib import contextmanager

from recipe_engine.config import List, Single
from recipe_engine.recipe_api import Property

TARGET_CPU = ['arm64', 'x64']

COMMIT_MESSAGE = '[gndoc] Update GN build arguments documentation'

DEPS = [
    'infra/auto_roller',
    'infra/cipd',
    'infra/fuchsia',
    'infra/jiri',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = {
    'category':
        Property(kind=str, help='Build category', default=None),
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
    'packages':
        Property(kind=List(basestring), help='Packages to build', default=[]),
}


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, project, manifest, remote,
             packages):
  api.jiri.ensure_jiri()

  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      project=project,
      patch_ref=patch_ref,
      patch_gerrit_url=patch_gerrit_url,
      patch_project=patch_project,
  )

  cipd_dir = api.path['start_dir'].join('cipd')
  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      api.cipd.ensure(cipd_dir, {
          'fuchsia/tools/gndoc/${platform}': 'latest',
      })

  project_dir = api.path['start_dir'].join(*project.split('/'))
  # Get the project list for linkifiying (need all projects).
  project_result = api.jiri.project()

  # Gather args for running gndoc tool.
  out_file = project_dir.join('docs', 'build_arguments.md')
  gndoc_cmd = [
      cipd_dir.join('gndoc'),
      '-key',
      'target_cpu',
      '-out',
      out_file,
      '-s',
      api.json.input(project_result.json.output),
  ]

  # Generate a gn args json file for each build target.
  for target in TARGET_CPU:
    # Run gn and generate json file
    args = [
        'target_cpu="%s"' % target,
        'fuchsia_packages=[%s]' % ','.join('"%s"' % pkg for pkg in packages),
    ]

    api.step('gn gen (%s)' % target, [
        api.path['start_dir'].join('buildtools', 'gn'),
        'gen',
        api.path['start_dir'].join('out', target),
        '--args=%s' % ' '.join(args),
    ])

    api.step(
        'gn args --list (%s)' % target,
        [
            api.path['start_dir'].join('buildtools', 'gn'), 'args',
            api.path['start_dir'].join('out', target), '--list', '--json'
        ],
        stdout=api.raw_io.output(
            leak_to=api.path['cleanup'].join('%s.json' % target)),
    )

    # Add targets to gndoc command
    gndoc_cmd.extend(["-in", api.path['cleanup'].join('%s.json' % target)])

  api.step("gndoc", gndoc_cmd)

  api.auto_roller.attempt_roll(
          gerrit_project=project,
          repo_dir=project_dir,
          commit_message=COMMIT_MESSAGE)


def GenTests(api):
  for project in ['garnet', 'peridot', 'topaz']:
    yield api.test(project + '_docs') + api.properties(
        manifest='fuchsia',
        project=project,
        remote='https://fuchsia.googlesource.com/manifest',
        packages=[project + '/packages/default'],
    ) + api.step_data(
        'check if done (0)', api.auto_roller.success()) + api.step_data(
            'jiri project',
            api.json.output([{
                "name": "build",
                "path": "/path/to/build",
                "relativePath": "build",
                "remote": "https://fuchsia.googlesource.com/build",
            }])) + api.step_data('gn args --list (x64)',
                                 api.json.output([{
                                     "current": {
                                         "file": "//" + project + "/out/x64/args.gn",
                                         "line": 1,
                                         "value": "\"x64\""
                                     },
                                     "default": {
                                         "value": "\"\""
                                     },
                                     "name": "target_cpu"
                                 }]))
