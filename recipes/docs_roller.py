# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for generating docs."""

from contextlib import contextmanager

from recipe_engine.config import List, Single
from recipe_engine.recipe_api import Property

TARGET_CPU = ['arm64', 'x64']

COMMIT_MESSAGE = '''\
[gndoc] Update GN build arguments documentation

Test: CQ
'''

DEPS = [
    'infra/auto_roller',
    'infra/cipd',
    'infra/fuchsia',
    'infra/jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = {
    'project':
        Property(kind=str, help='Jiri remote manifest project', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use'),
    'remote':
        Property(kind=str, help='Remote manifest repository'),
    'packages':
        Property(kind=List(basestring), help='Packages to build', default=[]),
    'run_gndoc':
        Property(kind=bool, help='Run gndoc', default=True),
}


def gen_gndoc(api, packages, project_dir):
  # Get the project list for linkifiying (need all projects).
  sources_path = api.path['cleanup'].join('projects.json')
  project_result = api.jiri.project(out=sources_path)

  # Gather args for running gndoc tool.
  out_file = project_dir.join('docs', 'gen', 'build_arguments.md')
  gndoc_cmd = [
      api.path['start_dir'].join('cipd', 'gndoc'),
      '-key',
      'target_cpu',
      '-out',
      out_file,
      '-s',
      sources_path,
  ]

  # Generate a gn args json file for each build target.
  for target in TARGET_CPU:
    # Run gn and generate json file
    args = [
        'target_cpu="%s"' % target,
        'fuchsia_packages=[%s]' % ','.join('"%s"' % pkg for pkg in packages),
    ]

    # The build directory is root_build_dir, as this will end up in the
    # generated documenation for any arg that is declared in this directory.
    # $root_build_dir is a clear way to indicate from where the arg is named.
    api.step('gn gen (%s)' % target, [
        api.path['start_dir'].join('buildtools', 'gn'),
        'gen',
        api.path['start_dir'].join('root_build_dir'),
        '--args=%s' % ' '.join(args),
    ])

    api.step(
        'gn args --list (%s)' % target,
        [
            api.path['start_dir'].join('buildtools', 'gn'), 'args',
            api.path['start_dir'].join('root_build_dir'), '--list', '--json'
        ],
        stdout=api.raw_io.output(
            leak_to=api.path['cleanup'].join('%s.json' % target)),
    )

    # Add targets to gndoc command
    gndoc_cmd.extend(["-in", api.path['cleanup'].join('%s.json' % target)])

  api.step("gndoc", gndoc_cmd)


def RunSteps(api, project, manifest, remote, packages, run_gndoc):
  api.jiri.ensure_jiri()

  cipd_dir = api.path['start_dir'].join('cipd')
  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      api.cipd.ensure(cipd_dir, {
          'fuchsia/tools/gndoc/${platform}': 'latest',
      })

  build_input = api.buildbucket.build.input
  api.fuchsia.checkout(
      manifest=manifest,
      remote=remote,
      build_input=build_input,
      project=project,
  )

  project_dir = api.path['start_dir'].join(*project.split('/'))

  if run_gndoc:
    with api.step.nest('gndoc'):
      gen_gndoc(api, packages, project_dir)

  api.auto_roller.attempt_roll(
      gerrit_project=project,
      repo_dir=project_dir,
      commit_message=COMMIT_MESSAGE)


def GenTests(api):
  roller_success = api.step_data('check if done (0)', api.auto_roller.success())

  def properties(project):
    return api.properties(
        manifest='fuchsia',
        project=project,
        remote='https://fuchsia.googlesource.com/' + project,
        packages=[project + '/packages/default'],
    )

  def gndoc_test_data(project):
    return api.step_data(
        'gndoc.jiri project',
        api.json.output([{
            "name": "build",
            "path": "/path/to/build",
            "relativePath": "build",
            "remote": "https://fuchsia.googlesource.com/build",
        }])) + api.step_data(
            'gndoc.gn args --list (x64)',
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

  yield (api.test('garnet_docs') +
    api.buildbucket.ci_build(
      git_repo='https://fuchsia.googlesource.com/garnet'
    ) +
    roller_success +
    properties('garnet') +
    gndoc_test_data('garnet')
  )

  yield (api.test('peridot_docs') +
    api.buildbucket.ci_build(
      git_repo='https://fuchsia.googlesource.com/peridot'
    ) +
    roller_success +
    properties('peridot') +
    gndoc_test_data('peridot')
  )

  yield (api.test('topaz_docs') +
    api.buildbucket.ci_build(
      git_repo='https://fuchsia.googlesource.com/topaz'
    ) +
    roller_success +
    properties('topaz') +
    gndoc_test_data('topaz')
  )
