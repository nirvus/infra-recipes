# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Rust toolchain."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re


DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/gsutil',
  'infra/jiri',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/file',
  'recipe_engine/step',
  'recipe_engine/url',
]

RUST_FUCHSIA_GIT = 'https://fuchsia.googlesource.com/third_party/rust'

PROPERTIES = {
  'url': Property(kind=str, help='Git repository URL', default=RUST_FUCHSIA_GIT),
  'ref': Property(kind=str, help='Git reference', default='refs/heads/master'),
  'revision': Property(kind=str, help='Revision', default=None),
}

BUILD_CONFIG = '''
[llvm]
optimize = true
static-libstdcpp = true
ninja = true
targets = "X86;AArch64"

[build]
target = ["x86_64-unknown-fuchsia", "aarch64-unknown-fuchsia"]
docs = false
extended = true
openssl-static = true

[install]
prefix = "{prefix}"
sysconfdir = "etc"

[rust]
optimize = true

[target.x86_64-unknown-fuchsia]
cc = "{cc}"
cxx = "{cxx}"
ar = "{ar}"
linker = "{cc}"

[target.aarch64-unknown-fuchsia]
cc = "{cc}"
cxx = "{cxx}"
ar = "{ar}"
linker = "{cc}"

[dist]
'''

CARGO_CONFIG = '''
[target.x86_64-unknown-fuchsia]
linker = "{linker}"
ar = "{ar}"
rustflags = ["-C", "link-arg=--target=x86_64-unknown-fuchsia", "-C", "link-arg=--sysroot={x86_64_sysroot}"]

[target.aarch64-unknown-fuchsia]
linker = "{linker}"
ar = "{ar}"
rustflags = ["-C", "link-arg=--target=aarch64-unknown-fuchsia", "-C", "link-arg=--sysroot={aarch64_sysroot}"]
'''


def RunSteps(api, url, ref, revision):
  api.gitiles.ensure_gitiles()
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()

  if not revision:
    revision = api.gitiles.refs(url).get(ref, None)
  cipd_pkg_name = 'fuchsia/rust/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  with api.context(infra_steps=True):
    api.jiri.init()
    api.jiri.import_manifest(
        'manifest/zircon',
        'https://fuchsia.googlesource.com/zircon',
        'zircon'
    )
    api.jiri.update()

    rust_dir = api.path['start_dir'].join('rust')
    api.git.checkout(url, rust_dir, ref=revision)

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
        'infra/cmake/${platform}': 'version:3.9.2',
        'infra/ninja/${platform}': 'version:1.8.2',
        'infra/swig/${platform}': 'version:3.0.12',
        'fuchsia/clang/${platform}': 'goma',
      })

  # Build Zircon sysroot.
  # TODO(mcgrathr): Move this into a module shared by all *_toolchain.py.
  zircon_dir = api.path['start_dir'].join('zircon')
  sysroot = {}
  for tc_arch, gn_arch in [('aarch64', 'arm64'), ('x86_64', 'x64')]:
    sysroot[tc_arch] = zircon_dir.join('build-%s' % gn_arch, 'sysroot')
    with api.context(cwd=zircon_dir):
      api.step('build %s sysroot' % tc_arch, [
        'make',
        '-j%s' % api.platform.cpu_count,
        'PROJECT=%s' % gn_arch,
        'sysroot',
      ])

  # build rust
  staging_dir = api.path.mkdtemp('rust')
  build_dir = staging_dir.join('build')
  api.file.ensure_directory('build', build_dir)
  pkg_dir = staging_dir.join('rust')

  config_file = build_dir.join('config.toml')
  api.file.write_text('write config.toml',
      config_file,
      BUILD_CONFIG.format(
          prefix=pkg_dir,
          cc=cipd_dir.join('bin', 'clang'),
          cxx=cipd_dir.join('bin', 'clang++'),
          ar=cipd_dir.join('bin', 'llvm-ar'),
      )
  )

  cargo_dir = staging_dir.join('.cargo')
  api.file.ensure_directory('.cargo', cargo_dir)
  api.file.write_text('write config',
      cargo_dir.join('config'),
      CARGO_CONFIG.format(
          linker=cipd_dir.join('bin', 'clang'),
          ar=cipd_dir.join('bin', 'llvm-ar'),
          x86_64_sysroot=sysroot['x86_64'],
          aarch64_sysroot=sysroot['aarch64'],
      ),
  )

  env = {
    'CFLAGS_%s-unknown-fuchsia' % arch: (
        '--target=%s-unknown-fuchsia --sysroot=%s' % (arch, sysroot))
    for arch, sysroot in sysroot.iteritems()
  }
  env['CARGO_HOME'] = cargo_dir
  env_prefixes = {'PATH': [cipd_dir, cipd_dir.join('bin')]}
  with api.context(cwd=build_dir, env=env, env_prefixes=env_prefixes):
    api.python(
      'rust install',
      rust_dir.join('x.py'),
      args=['install', '--config', config_file])

  # package rust
  step_result = api.step('rust version',
      [pkg_dir.join('bin', 'rustc'), '--version'],
      stdout=api.raw_io.output(),
      step_test_data=lambda:
      api.raw_io.test_api.stream_output('rustc 1.19.0-nightly (75b056812 2017-05-15)'))
  m = re.search(r'rustc ([0-9a-z.-]+)', step_result.stdout)
  assert m, 'Cannot determine Rust version'
  version = m.group(1)

  cipd_pkg_file = staging_dir.join('rust.cipd')

  api.cipd.build(
      input_dir=pkg_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy',
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'version': version,
        'git_repository': RUST_FUCHSIA_GIT,
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('rust', api.cipd.platform_suffix(), step_result.json.output['result']['instance_id']),
      unauthenticated_url=True
  )


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  for platform in ('linux', 'mac'):
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.step_data('cipd search fuchsia/rust/' + platform + '-amd64 ' +
                         'git_revision:'+revision,
                         api.json.output({'result': []})))
