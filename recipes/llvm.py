# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building LLVM."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/goma',
  'infra/gsutil',
  'infra/hash',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

TARGETS = ['arm64', 'x64']
TARGET_TO_ARCH = dict(zip(
    TARGETS,
    ['aarch64', 'x86_64'],
))

LLVM_PROJECT_GIT = 'https://fuchsia.googlesource.com/third_party/llvm-project'

PROPERTIES = {
  'url': Property(kind=str, help='Git repository URL', default=LLVM_PROJECT_GIT),
  'ref': Property(kind=str, help='Git reference', default='refs/heads/master'),
  'revision': Property(kind=str, help='Revision', default=None),
}


def RunSteps(api, url, ref, revision):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()

  if not revision:
    revision = api.gitiles.refs(url).get(ref, None)
  cipd_pkg_name = 'fuchsia/lib/llvm'
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      packages = {
        'infra/cmake/${platform}': 'version:3.9.2',
        'infra/ninja/${platform}': 'version:1.8.2',
        'fuchsia/clang/${platform}': 'goma',
      }
      api.cipd.ensure(cipd_dir, packages)

  with api.step.nest('ensure_sdk'):
    with api.context(infra_steps=True):
      sdk_dir = api.path['start_dir'].join('sdk')
      packages = {
        'fuchsia/sdk/${platform}': 'latest',
      }
      api.cipd.ensure(sdk_dir, packages)

  staging_dir = api.path.mkdtemp('llvm')
  pkg_dir = staging_dir.join('root')
  api.file.ensure_directory('create pkg root dir', pkg_dir)

  with api.context(infra_steps=True):
    llvm_dir = api.path['start_dir'].join('llvm-project')
    api.git.checkout(url, llvm_dir, ref=revision, submodules=True)

  # build llvm
  with api.goma.build_with_goma():
    for target, arch in TARGET_TO_ARCH.iteritems():
      build_dir = staging_dir.join('llvm_%s_build_dir' % target)
      api.file.ensure_directory('create %s llvm build dir' % target, build_dir)

      install_dir = staging_dir.join('llvm_%s_install_dir' % target)
      api.file.ensure_directory('create %s llvm install dir' % target, install_dir)

      with api.context(cwd=build_dir):
        api.step('configure %s llvm' % target, [
          cipd_dir.join('bin', 'cmake'),
          '-GNinja',
          '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
          '-DCMAKE_INSTALL_PREFIX=',
          '-DCMAKE_SYSTEM_NAME=Fuchsia',
          '-DCMAKE_C_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
          '-DCMAKE_CXX_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
          '-DCMAKE_ASM_COMPILER_LAUNCHER=%s' % api.goma.goma_dir.join('gomacc'),
          '-DCMAKE_C_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
          '-DCMAKE_C_COMPILER_TARGET=%s-fuchsia' % arch,
          '-DCMAKE_CXX_COMPILER=%s' % cipd_dir.join('bin', 'clang++'),
          '-DCMAKE_CXX_COMPILER_TARGET=%s-fuchsia' % arch,
          '-DCMAKE_ASM_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
          '-DCMAKE_ASM_COMPILER_TARGET=%s-fuchsia' % arch,
          '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
          '-DCMAKE_AR=%s' % cipd_dir.join('bin', 'llvm-ar'),
          '-DCMAKE_LINKER=%s' % cipd_dir.join('bin', 'ld.lld'),
          '-DCMAKE_NM=%s' % cipd_dir.join('bin', 'llvm-nm'),
          '-DCMAKE_OBJCOPY=%s' % cipd_dir.join('bin', 'llvm-objcopy'),
          '-DCMAKE_OBJDUMP=%s' % cipd_dir.join('bin', 'llvm-objdump'),
          '-DCMAKE_RANLIB=%s' % cipd_dir.join('bin', 'llvm-ranlib'),
          '-DCMAKE_STRIP=%s' % cipd_dir.join('bin', 'llvm-strip'),
          '-DCMAKE_SYSROOT=%s' % sdk_dir.join('arch', target, 'sysroot'),
          '-DLLVM_HOST_TRIPLE=%s-fuchsia' % arch,
          '-DLLVM_TARGETS_TO_BUILD=X86;ARM;AArch64',
          '-DLLVM_DISTRIBUTION_COMPONENTS=llvm-headers;LLVM',
          '-DLLVM_BUILD_LLVM_DYLIB=ON',
          '-DLLVM_ENABLE_LLD=ON',
          # TODO(BLD-182): we cannot enable this until llvm-strip supports -x
          #'-DLLVM_EXTERNALIZE_DEBUGINFO=ON',
          llvm_dir.join('llvm'),
        ])
        api.step('build %s llvm' % target,
                 [cipd_dir.join('ninja'), 'distribution',
                  '-j%s' % api.goma.recommended_goma_jobs])

        with api.context(env={'DESTDIR': install_dir}):
          api.step('install %s llvm' % target,
                   [cipd_dir.join('ninja'), 'install-distribution'])

      api.file.copytree('copy %s libs' % target, install_dir.join('lib'),
                        pkg_dir.join('arch', target, 'lib'))

    api.python('merge headers', api.resource('merge_headers.py'),
        args=[
          '--out', pkg_dir.join('pkg', 'llvm', 'include'),
          '--def1', '__aarch64__', '--def2', '__x86_64__',
          staging_dir.join('llvm_arm64_install_dir', 'include'),
          staging_dir.join('llvm_x64_install_dir', 'include'),
        ]
    )

  step_result = api.file.read_text('llvm-config.h',
      pkg_dir.join('pkg', 'llvm', 'include', 'llvm', 'Config', 'llvm-config.h'),
      test_data='#define LLVM_VERSION_STRING "7.0.0svn"')
  m = re.search(r'LLVM_VERSION_STRING "([0-9.-]+)', step_result)
  assert m, 'Cannot determine LLVM version'
  llvm_version = m.group(1)

  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=pkg_dir,
      install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/llvm.cipd_version')

  cipd_pkg_file = api.path['cleanup'].join('llvm.cipd')

  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': llvm_version,
        'git_repository': LLVM_PROJECT_GIT,
        'git_revision': revision,
      },
  )

  instance_id = step_result.json.output['result']['instance_id']
  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('lib', 'llvm', instance_id),
      unauthenticated_url=True
  )


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  yield (api.test('existing_pkg') +
         api.gitiles.refs('refs', ('refs/heads/master', revision)))
  yield (api.test('new_revision') +
         api.gitiles.refs('refs', ('refs/heads/master', revision)) +
         api.step_data('cipd search fuchsia/lib/llvm ' +
                       'git_revision:' + revision,
                       api.json.output({'result': []})))
