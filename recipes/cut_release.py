# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for automatically cutting new release branches."""


from recipe_engine.config import Enum, List, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/git',
  'infra/lkgs',
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/time',
]


PROPERTIES = {
    'release_repository':
        Property(
            kind=str, help='The repository to cut a new release branch on.'),
    'release_names':
        Property(
            kind=List(basestring), help='The overarching names for each release.'),
    'release_targets':
        Property(
            kind=List(basestring),
            help='The target platforms for the releases, typically an arch (e.g.'
                 ' arm64, x64).'),
    'reference_builders':
        Property(
            kind=List(basestring),
            help='Builders to check for the last known good snapshot.'),
}


COMMIT_MESSAGE = """\
[release] Cut release branch {branch_name}
"""

BRANCH_NAME = 'refs/heads/releases/{name}-{target}/{date}'


def RunSteps(api, release_repository, release_names, release_targets,
             reference_builders):
  # Note that releases_names, releases_targets, and reference_builders are
  # effectively a list of tuples, but are instead represented as lists.
  assert len(release_names) == len(release_targets)
  assert len(release_names) == len(reference_builders)

  api.lkgs.ensure_lkgs(version='latest')
  with api.context(infra_steps=True):
    # Check out releases repository so we can push new branches to it.
    release_path = api.path['start_dir'].join('releases')
    api.git.checkout(
        url=release_repository,
        path=release_path,
        ref='master',
    )

    # Cut releases for all given (release name, release target, reference
    # builder) tuples passed in as properties.
    snapshot_file = release_path.join('snapshot')
    for i in range(len(release_names)):
      name = release_names[i]
      target = release_targets[i]
      builder = reference_builders[i]

      # Obtain the last-known-good-snapshot for the reference builder.
      api.lkgs(
          step_name='lkgs %s' % builder,
          builder=builder,
          output_file=snapshot_file,
      )

      # Commit and push the snapshot.
      date = api.time.utcnow().date().isoformat()
      with api.context(cwd=release_path):
        api.git('add', snapshot_file)
        branch_name = BRANCH_NAME.format(
            name=name,
            target=target,
            date=date,
        )
        api.git.commit(message=COMMIT_MESSAGE.format(branch_name=branch_name))
        api.git('push', 'origin', 'HEAD:%s' % branch_name)
        # Drop the commit we just created so we can continue to
        # manipulate the same repository.
        api.git('reset', '--hard', 'HEAD~1')


def GenTests(api):
  yield api.test('basic') + api.properties(
    release_repository='https://fuchsia.googlesource.com/releases',
    release_names=['garnet'],
    release_targets=['x64'],
    reference_builders=['garnet-x64-release-qemu_kvm'],
  )
