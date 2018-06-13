# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for automatically updating Dart 3p packages."""


from recipe_engine.config import Enum, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/auto_roller',
  'infra/git',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/json',
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

TEST=CQ
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

    # Read the dart-pkg entry in the dart manifest.
    dart_pkg_entry = api.jiri.read_manifest_element(
        manifest=api.path['start_dir'].join('topaz', 'manifest', 'dart'),
        element_type='project',
        element_name='third_party/dart-pkg',
    )

    # Checkout master for third_party/dart-pkg.
    # We check out master here because this roller is updating the
    # third_party/dart-pkg repository itself, and we're checking out Topaz which
    # has a pinned version of the repository. In order to ensure the patch is
    # accurate, we checkout master. Note that we cannot simply check out
    # the repository without Topaz because update_3p_packages.py depends on a
    # full Topaz checkout.
    dart_pkg_dir = api.path['start_dir'].join(dart_pkg_entry.get('path'))
    with api.context(cwd=dart_pkg_dir):
      api.git('checkout', '--detach', 'origin/master')

    # Execute script to update 3p packages.
    changes = api.python(
        name='update dart 3p packages',
        script=api.path['start_dir'].join('scripts', 'dart',
                                          'update_3p_packages.py'),
        args=['--changelog', api.raw_io.output_text()],
    ).raw_io.output_text

    # Land the changes.
    api.auto_roller.attempt_roll(
        gerrit_project='third_party/dart-pkg',
        repo_dir=dart_pkg_dir,
        commit_message=COMMIT_MESSAGE.format(changes=changes),
        commit_untracked=True,
    )


def GenTests(api):
  yield (api.test('basic') +
         api.jiri.read_manifest_element(api,
             manifest=api.path['start_dir'].join('topaz', 'manifest', 'dart'),
             element_type='project',
             element_name='third_party/dart-pkg',
             test_output={
                 'remote': 'https://fuchsia.googlesource.com/third_party/dart-pkg',
                 'path': 'third_party/dart-pkg/pub',
             },
         ) +
         api.step_data('check if done (0)', api.auto_roller.success()))
