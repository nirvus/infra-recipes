# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Jiri."""

from recipe_engine.config import ReturnSchema, Single
from recipe_engine.recipe_api import Property
from recipe_engine import config


DEPS = [
  'infra/cipd',
  'infra/jiri',
  'infra/git',
  'infra/go',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/shutil',
  'recipe_engine/step',
  'recipe_engine/time',
]

PROPERTIES = {
  'category': Property(kind=str, help='Build category', default=None),
  'patch_gerrit_url': Property(kind=str, help='Gerrit host', default=None),
  'patch_project': Property(kind=str, help='Gerrit project', default=None),
  'patch_ref': Property(kind=str, help='Gerrit patch ref', default=None),
  'patch_storage': Property(kind=str, help='Patch location', default=None),
  'patch_repository_url': Property(kind=str, help='URL to a Git repository',
                            default=None),
  'manifest': Property(kind=str, help='Jiri manifest to use'),
  'remote': Property(kind=str, help='Remote manifest repository'),
  'target': Property(kind=str, help='Target to build'),
}

RETURN_SCHEMA = ReturnSchema(
  got_revision=Single(str)
)


def RunSteps(api, category, patch_gerrit_url, patch_project, patch_ref,
             patch_storage, patch_repository_url, manifest, remote, target):
  api.jiri.ensure_jiri()

  api.jiri.init()
  api.jiri.import_manifest(manifest, remote, overwrite=True)
  api.jiri.clean_project(branches=True)
  api.jiri.update(gc=True)

  if patch_ref is not None:
    api.jiri.patch(patch_ref, host=patch_gerrit_url)

  api.go.ensure_go()

  jiri_dir = api.path['start_dir'].join(
      'go', 'src', 'fuchsia.googlesource.com', 'jiri')
  git2go_dir = jiri_dir.join('vendor', 'github.com', 'libgit2', 'git2go')
  libgit2_dir = git2go_dir.join('vendor', 'libgit2')

  with api.step.nest('ensure_packages'):
    with api.step.context({'infra_step': True}):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
        'fuchsia/tools/cmake/${platform}': 'latest',
        'fuchsia/tools/ninja/${platform}': 'latest',
      })

  build_dir = libgit2_dir.join('build')
  api.shutil.makedirs('build', build_dir)
  with api.step.context({'cwd': build_dir}):
    api.step('configure libgit2', [
      cipd_dir.join('bin', 'cmake'),
      '-GNinja',
      '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
      '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
      '-DCMAKE_C_FLAGS=-fPIC',
      '-DTHREADSAFE=ON',
      '-DBUILD_CLAR=OFF',
      '-DBUILD_SHARED_LIBS=OFF',
      libgit2_dir,
    ])
    api.step('build libgit2', [cipd_dir.join('ninja')])

  revision = api.jiri.project('jiri').json.output[0]['revision']
  build_time = api.time.utcnow().isoformat()

  ldflags = "-X \"fuchsia.googlesource.com/jiri/version.GitCommit=%s\" -X \"fuchsia.googlesource.com/jiri/version.BuildTime=%s\"" % (revision, build_time)
  gopath = api.path['start_dir'].join('go')

  with api.step.context({'env': {'GOPATH': gopath}}):
    api.go('build jiri', '-ldflags', ldflags, '-a',
           'fuchsia.googlesource.com/jiri/cmd/jiri')

  with api.step.context({'env': {'GOPATH': gopath}}):
    api.go('test jiri', 'fuchsia.googlesource.com/jiri/cmd/jiri')

  return RETURN_SCHEMA.new(got_revision=revision)


def GenTests(api):
  yield api.test('ci') + api.properties(
      manifest='jiri',
      remote='https://fuchsia.googlesource.com/manifest',
      target='linux-amd64',
  )
  yield api.test('cq_try') + api.properties.tryserver(
      gerrit_project='jiri',
      patch_gerrit_url='fuchsia-review.googlesource.com',
      manifest='jiri',
      remote='https://fuchsia.googlesource.com/manifest',
      target='linux-amd64',
  )
