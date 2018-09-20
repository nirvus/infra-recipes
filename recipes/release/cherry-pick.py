# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for cherry-picking changes into a release."""

import json
import re
import os

from recipe_engine.config import List, Single
from recipe_engine.recipe_api import Property

DEPS = [
    'infra/git',
    'infra/auto_roller',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
]

PROPERTIES = {
    'branch':
        Property(
            kind=str,
            help='Branch on the repository to push the release snapshot',
            default=None),
    'version':
        Property(
            kind=str,
            help='Current version (YYYYMMDD_##_RC##) to apply cherry-picks to',
            default=None),
    'cherry_picks':
        Property(
            kind=List(basestring),
            help=
            'List of cherry-picks to apply in the form ["project1/ref1", "project2/ref2"]',
            default=None),
    'remote':
        Property(
            kind=str,
            help='Remote snapshot repository to checkout',
            default=None),
    'gerrit_project':
        Property(
            kind=str,
            help='Name of the Gerrit project corresponding to the repository',
            default=None),
}

COMMIT_MESSAGE = """[cherrypick] Cherry-pick onto {version}

Cherry-picks:
{cherry_picks}
"""


def RunSteps(api, branch, cherry_picks, remote, gerrit_project, version):
  with api.context(infra_steps=True):
    if len(cherry_picks) == 0:
      raise api.step.StepFailure('No cherry-picks supplied')
    release_path = api.path['start_dir'].join('releases')
    api.git.checkout(
        url=remote,
        path=release_path,
        ref=version,
    )

    cherry_pick_file = release_path.join('cherrypick.json')
    existing_cherry_picks = None

    # Read existing cherry-picks if they exist
    if api.path.exists(cherry_pick_file):
      existing_cherry_picks = api.json.read(
          name='read cherry-pick file', path=cherry_pick_file).json.output

    # If the cherry pick file is empty or didn't exist, create an empty dict
    if existing_cherry_picks is None:
      existing_cherry_picks = {}

    # For each cherry pick passed as a recipe property
    for cherry_pick in cherry_picks:
      project, ref = cherry_pick.split("/")
      # If the project doesn't exist add it
      if project not in existing_cherry_picks:
        existing_cherry_picks[project] = []
      # If the ref doesn't exist add it
      if ref not in existing_cherry_picks[project]:
        existing_cherry_picks[project].append(ref)

    api.file.write_raw('write cherry-pick file', cherry_pick_file,
                       json.dumps(existing_cherry_picks))

    message = COMMIT_MESSAGE.format(
        cherry_picks=''.join(cherry_picks), version=version)

    api.auto_roller.attempt_roll(
        gerrit_project=gerrit_project,
        repo_dir=release_path,
        commit_message=message,
        # This 'git add's all files in the git checkout.  We should ensure
        # that the checkout is clean before calling attempt_roll.
        commit_untracked=True,
        dry_run=True,
    )

    # Extract the version into TWO match groups
    m = re.match(r"^(\d{8}_\d{2}_RC)(\d{2})$", version)
    # Increment the RC # in the second match group
    # Recombine to form the new version
    tag = m.groups()[0] + str(int(m.groups()[1]) + 1).zfill(2)

    with api.context(cwd=release_path):
      api.git('tag', tag)
      api.git('push', 'origin', 'HEAD:%s' % branch)
      api.git('push', '--tags')


def GenTests(api):
  yield api.test('one cherrypick') + api.properties(
      branch="master",
      version="20180830_00_RC00",
      cherry_picks=['topaz/fc4dc762688d2263b254208f444f5c0a4b91bc07'],
      remote="https://fuchsia.googlesource.com/releases",
      project="releases") + api.step_data('check if done (0)',
                                          api.auto_roller.success())

  yield api.test('no cherrypick') + api.properties(
      branch="master",
      version="20180830_00_RC00",
      cherry_picks=[],
      remote="https://fuchsia.googlesource.com/releases",
      project="releases")

  yield api.test('has cherrypick file') + api.properties(
      branch="master",
      version="20180830_00_RC00",
      cherry_picks=['topaz/fc4dc762688d2263b254208f444f5c0a4b91bc07'],
      remote="https://fuchsia.googlesource.com/releases",
      project="releases") + api.step_data(
          'check if done (0)', api.auto_roller.success()) + api.path.exists(
              api.path['start_dir'].join('releases', 'cherrypick.json'))
