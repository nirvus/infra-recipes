# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for running Tricium clang-format analyzer."""

from contextlib import contextmanager

from recipe_engine.recipe_api import Property

DEPS = [
    'infra/clang_tidy',
    'infra/git',
    'infra/jiri',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/tricium',
]

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

PROPERTIES = {
    'project':
        Property(kind=str, help='Gerrit patch ref', default=None),
    'manifest':
        Property(kind=str, help='Jiri manifest to use', default=None),
    'checks':
        Property(
            kind=List(basestring),
            help='Checks for clang-tidy to run',
            default=['*']),
}


def RunSteps(api, project, manifest, checks):
  api.clang_tidy.ensure_clang()
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
        build_input=api.buildbucket.build.input)

  checkout_dir = api.path['start_dir'].join(project)
  compile_commands = api.clang_tidy.gen_compile_commands(checkout_dir)

  errors = []
  with api.step.nest('clang-tidy'):
    for f in api.tricium.paths:
      errors.append(api.clang_tidy.run(f, f, compile_commands, checks))

  # We iterate through all produced error sets...
  for path_errors in errors:
    # ...and iterate through all checks that had errors...
    for check in path_errors:
      # ...and for each check, iterate through all the errors it produced...
      for err in path_errors[check]:
        # ...and extract the information from that error for a comment.
        sline, schar = api.clang_tidy.get_line_from_offset(
            err['FilePath'], err['FileOffset'])
        api.tricium.add_comment(
            'ClangTidy/%s' % err['DiagnosticName'],
            '%s: %s' % (err['DiagnosticName'], err['Message']),
            err['FilePath'],
            start_line=sline,
            start_char=schar,
        )

  api.tricium.write_comments()


def GenTests(api):
  diff_output = '''path/to/file
other/path/to/file'''
  read_output = '''test
newline output
'''
  has_errors = '''- DiagnosticName:  "fuchsia-default"
  Message:         "error"
  FileOffset:      1
  FilePath:        "path/to/file"
'''

  has_errors_json = [{
      'FileOffset': 1,
      'DiagnosticName': 'fuchsia-default',
      'Message': 'error',
      'FilePath': 'path/to/file'
  }]

  yield (api.test('default') + api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/topaz',) + api.properties(
          manifest='project/topaz',
          project='topaz',
          repository='https://fuchsia.googlesource.com/topaz',
          ref='HEAD',
          paths=['path/to/file', 'other/path/to/file']) + api.step_data(
              'clang-tidy.path/to/file.load yaml', stdout=api.json.output('')) +
         api.step_data(
             'clang-tidy.other/path/to/file.load yaml',
             stdout=api.json.output(has_errors_json)))
