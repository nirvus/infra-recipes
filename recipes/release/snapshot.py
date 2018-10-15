# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for automatically creating jiri snapshots from manifest commit."""

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

import re

DEPS = [
    'infra/git',
    'infra/lkgs',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
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

TAG_FORMAT = """{date}_{release:0>2}_RC{release_candidate:0>2}"""

LATEST_ROLLUP_TAG = """LATEST_ROLLUP"""

COMMIT_MESSAGE = """\
[release] {tag}
"""


def GetNextReleaseTag(api, remote):
  date = api.time.utcnow().date().strftime('%Y%m%d')
  # Get current tags for today.
  # This does not require being inside a git checkout,
  # ls-remote functions outside of the tree when given
  # a remote.
  step_result = api.git(
      'ls-remote',
      '-q',
      '-t',
      remote,
      '*%s*' % date,
      stdout=api.raw_io.output(),
      step_test_data=lambda: api.raw_io.test_api.stream_output('''
      cc83301b8cf7ee60828623904bbf0bd310fde349	refs/tags/20180920_00_RC00
      2bdcf7c40c23c3526092f708e28b0ba98f8fe4cd	refs/tags/20180920_00_RC01'''))
  step_result.presentation.logs['stdout'] = step_result.stdout.split('\n')
  # Find all the current release_versions
  m = re.findall(r'\d{8}_(\d{2})_RC00$', step_result.stdout, re.MULTILINE)
  # Find the max release_version
  release_version = -1
  for match in m:
    release_version = max(int(match), release_version)

  # Increment the release_version for this cut
  return TAG_FORMAT.format(
      date=date, release=str(release_version + 1), release_candidate=0)


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
    cherry_pick_file = release_path.join('cherrypick.json')

    # Obtain the last-known-good-snapshot for the builders.
    api.lkgs(
        step_name='lkgs',
        builder=builders,
        output_file=snapshot_file,
    )

    # TODO(nmulcahey): Fetch previous snapshot, ensure today's is newer, else exit.

    tag = GetNextReleaseTag(api, remote)
    # Commit and push the snapshot.
    with api.context(cwd=release_path):
      api.git('add', snapshot_file)
      # Remove an existing cherrypick file if it exists
      if api.path.exists(cherry_pick_file):
        api.git('rm', cherry_pick_file)
      api.git.commit(message=COMMIT_MESSAGE.format(tag=tag))
      api.git('tag', tag)
      api.git('tag', LATEST_ROLLUP_TAG)
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

  yield api.test('has existing cherrypick file') + api.properties(
      builders=['garnet-x64-release-qemu_kvm'],
      remote="http://fuchsia.googlesource.com/garnet",
      branch="master",
  ) + api.path.exists(api.path['start_dir'].join('releases', 'cherrypick.json'))
