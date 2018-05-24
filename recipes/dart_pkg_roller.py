# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for automatically updating Dart 3p packages."""


from recipe_engine.config import Enum, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/auto_roller',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]


# Note that this recipe accepts no properties because the recipe itself is quite
# specific, and its required configuration is encoded entirely in the logic.
PROPERTIES = {}


COMMIT_MESSAGE = """\
[roll] Update 3p packages

{changes}
"""


def RunSteps(api):
  api.jiri.ensure_jiri()

  with api.context(infra_steps=True):
    # Check out Topaz, as the update script depends on it.
    api.jiri.checkout(
        manifest='manifest/topaz',
        remote='https://fuchsia.googlesource.com/topaz',
        project='topaz',
    )

    # Execute script to update 3p packages.
    changes = api.python(
        name='update dart 3p packages',
        script=api.path['start_dir'].join('scripts', 'dart',
                                          'update_3p_packages.py'),
        args=['--changelog', api.raw_io.output_text()],
    ).raw_io.output_text

    # Land the changes.
    # TODO(mknyszek): Get the actual path for dart-pkg out of the manifest/dart
    # manifest.
    dart_pkg_dir = api.path['start_dir'].join('third_party', 'dart-pkg', 'pub')
    api.auto_roller.attempt_roll(
        gerrit_project='third_party/dart-pkg',
        repo_dir=dart_pkg_dir,
        commit_message=COMMIT_MESSAGE.format(changes=changes),
        commit_untracked=True,
    )


def GenTests(api):
  yield (api.test('basic') +
         api.step_data('check if done (0)', api.auto_roller.success()))
