# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for running Tricium FuchsiaFormat analyzer."""

from recipe_engine.config import Enum, List
from recipe_engine.recipe_api import Property

import collections

DEPS = [
    'infra/git',
    'infra/jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/tricium',
]

# namedtuple representing a formatter.
# |category| is the name of the formatter.
# |args| is a list of arguments to pass the formatter executable.
# |path| is the path from the cipd root to the formatter executable.
# |warning| is the warning Tricium will emit (modulo the file name).
Formatter = collections.namedtuple('FormatterType',
                                   ('category', 'args', 'path', 'warning'))
ClangFormat = Formatter(
    category='ClangFormat',
    args=['-style=file', '-fallback-style=Google', '-sort-includes', '-i'],
    path=('bin', 'clang-format'),
    warning=
    'File not formatted properly.\nRun the following to format:\n\nclang-format -i %s',
)

# TODO(juliehockett): Come up with a plan for addressing and integrating
# upstream formatter changes.
GNFormat = Formatter(
    category='GNFormat',
    args=['format'],
    path=['gn'],
    warning=
    'File not formatted properly.\nRun the following to format:\n\ngn format %s',
)

FORMATTERS = [ClangFormat]

EXT_TO_FORMATTER = {
    '.c': [ClangFormat],
    '.cc': [ClangFormat],
    '.cpp': [ClangFormat],
    '.h': [ClangFormat],
    '.hh': [ClangFormat],
    '.hpp': [ClangFormat],
    '.gn': [GNFormat],
    '.gni': [GNFormat],
    '.ts': [ClangFormat],
}

PROPERTIES = {
    'project':
        Property(kind=str, help='Project name', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use', default=None),
    'formatters':
        Property(
            kind=List(basestring), help='Formatters to be run', default=[]),
}


def RunSteps(api, project, manifest, formatters):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    # TODO(juliehockett): This is a hack to make the checkout work as expected, since
    # Tricium still uses the v1 scheduling API and thus doesn't set the Gerrit project.
    # Remove this once we fully switch Tricium over to the v2 API.
    api.buildbucket.build.input.gerrit_changes[0].project = project

    api.jiri.checkout(
        manifest=manifest,
        remote=api.tricium.repository,
        project=project,
        build_input=api.buildbucket.build.input,
        run_hooks=False)

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('fuchsia/clang/${platform}', 'goma')
      pkgs.add_package('gn/gn/${platform}', 'latest')
      api.cipd.ensure(cipd_dir, pkgs)

  project_dir = api.path['start_dir'].join(*project.split('/'))

  with api.context(cwd=project_dir):
    paths = api.git(
        'show',
        '--name-only',
        '--pretty=',
        name='get changed files',
        stdout=api.raw_io.output()).stdout.strip().split('\n')

    for f in paths:
      _, ext = api.path.splitext(f)
      if ext not in EXT_TO_FORMATTER:
        continue

      for formatter in EXT_TO_FORMATTER[ext]:
        # Check that this formatter is on for this run.
        if formatter.category not in formatters:
          continue  # pragma: no cover

        # Run the formatter tool.
        cmd = [cipd_dir.join(*formatter.path)] + formatter.args + [f]
        api.step('formatting %s' % f, cmd)
        diff_result = api.git(
            'diff',
            '--name-only',
            name='check %s formatting' % f,
            stdout=api.raw_io.output())

        if diff_result.stdout:
          api.tricium.add_comment('Format/%s' % formatter.category,
                                  formatter.warning % f, f)
          api.git('reset', '--hard', name='reset %s' % f)

  api.tricium.write_comments(dump=True)


def GenTests(api):

  show_output = '''other/path/to/file.c\npath/to/file.h\ngnfile.gn\n'''
  diff_output = '''path/to/file.h'''

  yield (api.test('default') + api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/topaz',) + api.properties(
          manifest='manifest/topaz',
          project='topaz',
          repository='https://fuchsia.googlesource.com/topaz',
          ref='refs/changes/12345/2',
          formatters=['ClangFormat', 'GNFormat']) + api.step_data(
              'get changed files', api.raw_io.stream_output(show_output)) +
         api.step_data('check path/to/file.h formatting',
                       api.raw_io.stream_output(diff_output)) + api.step_data(
                           'check other/path/to/file.c formatting',
                           api.raw_io.stream_output("")))

  yield (api.test('no_formatters') + api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/tools',) + api.properties(
          manifest='manifest/minimal',
          project='tools',
          repository='https://fuchsia.googlesource.com/tools',
          ref='refs/changes/12345/2',
          paths=['path/to/file.cpp']))
