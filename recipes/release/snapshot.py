# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for automatically creating jiri snapshots from manifest commit."""

from recipe_engine.config import List
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
    'branch':
        Property(
            kind=str,
            help='Branch on the repository to push the release snapshot',
            default=None),
    'builders':
        Property(
            kind=List(basestring),
            help='Builders to check for the last known good snapshot.',
            default=[]),
    'remote':
        Property(
            kind=str,
            help='Remote snapshot repository to checkout',
            default=None),
}

TAG_FORMAT = """%s_%02d_RC%02d"""

COMMIT_MESSAGE = """\
[release] {tag}
"""


# TODO(nmulcahey): Allow multiple cuts a day by fetching
# existing tags and incrementing the release number.
def GetNextReleaseTag(api):
  date = api.time.utcnow().date().strftime('%Y%m%d')
  return TAG_FORMAT.format(date, 0, 0)


def RunSteps(api, branch, builders, remote):
  api.lkgs.ensure_lkgs(version='latest')
  with api.context(infra_steps=True):
    # Check out releases repository so we can push new branches to it.
    release_path = api.path['start_dir'].join('releases')
    api.git.checkout(
        url=remote,
        path=release_path,
        ref=branch,
    )

    snapshot_file = release_path.join('snapshot')

    # Obtain the last-known-good-snapshot for the builders.
    api.lkgs(
        step_name='lkgs',
        builder=builders,
        output_file=snapshot_file,
    )

    # TODO(nmulcahey): Fetch previous snapshot, ensure today's is newer, else exit.

    # Commit and push the snapshot.
    with api.context(cwd=release_path):
      tag = GetNextReleaseTag(api)
      api.git('add', snapshot_file)
      api.git.commit(message=COMMIT_MESSAGE.format(tag=tag))
      api.git('tag', tag, '-am', tag)
      api.git('push', 'origin', 'HEAD:%s' % branch)
      api.git('push', '--tags')


def GenTests(api):
  yield api.test('one builder') + api.properties(
      builders=['garnet-x64-release-qemu_kvm'],
      remote="http://fuchsia.googlesource.com/garnet",
      branch="master",
  )

  yield api.test('many builders') + api.properties(
      builders=['garnet-x64-release-qemu_kvm', 'garnet-arm64-release-qemu_kvm'],
      remote="http://fuchsia.googlesource.com/garnet",
      branch="master",
  )

  yield api.test('zero builders') + api.properties(
      builders=[],
      remote="http://fuchsia.googlesource.com/garnet",
      branch="master",
  )

  yield api.test('invalid builder') + api.properties(
      builders=['this-is-an-invalid-builder-name-that-should-never-exist'],
      remote="http://fuchsia.googlesource.com/garnet",
      branch="master",
  )

  yield api.test('one builder of many invalid') + api.properties(
      builders=[
          'garnet-x64-release-qemu_kvm',
          'this-is-an-invalid-builder-name-that-should-never-exist'
      ],
      remote="http://fuchsia.googlesource.com/garnet",
      branch="master",
  )
