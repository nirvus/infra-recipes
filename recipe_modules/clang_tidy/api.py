# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine.config import List


class ClangTidyApi(recipe_api.RecipeApi):
  """ClangTidyApi provides support for ClangTidy."""

  def __init__(self, *args, **kwargs):
    super(ClangTidyApi, self).__init__(*args, **kwargs)

  def ensure_clang(self):
    with self.m.context(infra_steps=True):
      cipd_dir = self.m.path['start_dir'].join('cipd')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('fuchsia/clang/${platform}', 'goma')
      pkgs.add_package('fuchsia/buildtools/ninja/${platform}', 'latest')
      pkgs.add_package('gn/gn/${platform}', 'latest')
      self.m.cipd.ensure(cipd_dir, pkgs)

  def gen_compile_commands(self, checkout_dir):
    build_dir = self.m.path['cleanup'].join('out', 'Default')
    compile_commands = build_dir.join('compile_commands.json')
    with self.m.step.nest('generate compile_commands.json'):
      with self.m.context(cwd=checkout_dir):
        self.m.step('gn gen', [
            self.m.path['start_dir'].join('cipd', 'gn'),
            'gen',
            build_dir,
            '--export-compile-commands',
        ])

    return compile_commands

  def get_line_from_offset(self, f, offset):
    """Get the file line and char number from a file offset.

    Clang-Tidy emits warnings that mark the location of the error by the char
    offset from the beginning of the file. This converts that number into a line
    and char position.

    Args:
      filename (str): Path to file.
      offset (int): Offset to convert.
    """
    file_data = self.m.file.read_text(
        'read %s' % f, f, test_data='''test
newlineoutput''')
    line = 1
    char = 1
    for i, c in enumerate(file_data):
      if i + 1 == offset:
        return line, char
      if c == '\n':
        line += 1
        char = 1
      else:
        char += 1
    return 0, 0

  def run(self, step_name, filename, compile_commands, checks=['*']):
    """Runs clang-tidy on the specified file and returns parsed json output.

    TODO(juliehockett): Consider packaging and using the run_clang_tidy script.

    Args:
      filename (str): Path to file on which clang-tidy should be run.
      compile_commands (str): Path to dir containing compile_commands.json.
      checks (List): List of checks to run for clang-tidy (default is whatever
        is specified in the .clang-tidy file).
    """
    assert type(checks) == list
    assert len(checks) > 0
    with self.m.step.nest(step_name):
      warnings_file = self.m.path['cleanup'].join('clang_tidy_fixes.yaml')
      clang_tidy_cmd = [
          self.m.path['start_dir'].join('cipd', 'clang', 'bin', 'clang-tidy'),
          '-p',
          compile_commands,
          '--checks=%s' % ','.join(checks),
          '--export-fixes',
          warnings_file,
          filename,
      ]

      step_result = self.m.step('clang-tidy %s' % filename, clang_tidy_cmd)
      return self._parse_warnings(warnings_file)

  def _parse_warnings(self, warnings_file):
    """Parse all warnings output by clang-tidy.

    Clang-Tidy issues warnings as follows:
      - DiagnosticName:  'check name'
        Message:         'error message'
        FileOffset:      <offset (int)>
        FilePath:        'file path'
        Replacements:
          - FilePath:        'replacement file path'
            Offset:          <replacement start offset (int)>
            Length:          <replacement length (int)>
            ReplacementText: 'replacement text'

    Args:
      raw_warnings (str): YAML-encoded warnings as output by the clang-tidy binary

    Returns:
      A dict of parsed warnings by check.
        Schema:
          {
            '<check name>': [
                {
                  'DiagnosticName':   'check name'
                  'Message':          'error message',
                  'StartLine':         <error start line (int)>,
                  'StartChar':         <error start char (int)>,
                  'Replacements': [
                      {
                        'File':       'replacement file path',
                        'StartLine':  <replacement start line (int)>,
                        'StartChar':  <replacement start char (int)>,
                        'EndLine':    <replacement end line (int)>,
                        'EndChar':    <replacement end char (int)>,
                        'Text':       'replacement text'
                      },
                      ...
                    ]
                },
                ...
              ],
            '<other check name>': [ ... ]
          }
    """
    parsed_results = self.m.python(
        'load yaml',
        self.resource('parse_yaml.py'),
        args=[warnings_file],
        stdout=self.m.json.output(),
        venv=self.resource('clang-tidy.vpython')).stdout
    if not parsed_results:
      return {}
    all_warnings = {}
    for warning in parsed_results:
      if warning['DiagnosticName'] not in all_warnings:
        all_warnings[warning['DiagnosticName']] = []
      all_warnings[warning['DiagnosticName']].append(warning)
    return all_warnings
