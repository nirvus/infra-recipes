# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'clang_tidy',
    'fuchsia',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def RunSteps(api):
  api.clang_tidy.ensure_clang()
  checkout_dir = api.fuchsia.checkout(
      build_input=api.buildbucket.build.input,
      manifest='manifest/minimal',
      remote='tools',
  ).root_dir
  compile_commands = api.clang_tidy.gen_compile_commands(checkout_dir)

  all_checks = api.clang_tidy.run('step one', 'path/to/file', compile_commands)
  one_check = api.clang_tidy.run('step two', 'other/path/to/file',
                                 compile_commands,
                                 ['-*', 'fuchsia-default-arguments'])

  api.clang_tidy.get_line_from_offset('path/to/file', 12)
  api.clang_tidy.get_line_from_offset('other/path/to/file', 65)


def GenTests(api):
  read_output = '''test
newline output
'''

  has_errors = '''- DiagnosticName:  'check'
  Message:         'error'
  FileOffset:      1
  FilePath:        'path/to/file'
'''
  has_errors_json = [{
      'FileOffset': 1,
      'DiagnosticName': 'check',
      'Message': 'error',
      'FilePath': 'path/to/file'
  }]

  yield (api.test('basic') +
    api.buildbucket.try_build(
      git_repo='https://fuchsia.googlesource.com/tools'
    ) +
    api.step_data(
      'step one.load yaml', stdout=api.json.output(has_errors_json)) +
         api.step_data('step two.load yaml', stdout=api.json.output(''))
  )
