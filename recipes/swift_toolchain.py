# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Swift toolchain."""

from contextlib import contextmanager

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property

import re

DEPS = [
  'infra/cipd',
  'infra/git',
  'infra/gitiles',
  'infra/goma',
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

SWIFT_FUCHSIA_GIT = 'https://fuchsia.googlesource.com/third_party/swift'

PROPERTIES = {
  'url': Property(kind=str, help='Git repository URL', default=SWIFT_FUCHSIA_GIT),
  'ref': Property(kind=str, help='Git reference', default='refs/heads/upstream/fuchsia_release'),
  'revision': Property(kind=str, help='Revision', default=None),
  'goma_dir': Property(kind=str, help='Path to goma', default=None),
}

MANIFEST_FILE = """lib/libswiftCore.so=libswiftCore.so
lib/libswiftGlibc.so=libswiftGlibc.so
lib/libswiftSwiftOnoneSupport.so=libswiftSwiftOnoneSupport.so
lib/libswiftRemoteMirror.so=libswiftRemoteMirror.so
"""

PRESET_FILE = """
#===------------------------------------------------------------------------===#
# Fuchsia Mixins
#===------------------------------------------------------------------------===#
[preset: mixin_fuchsia_build]
fuchsia
extra-stdlib-deployment-targets=fuchsia-aarch64,fuchsia-x86_64
fuchsia-toolchain-path=%(clang_path)s
fuchsia-icu-uc-include=%(fuchsia_icu_uc)s
fuchsia-icu-i18n-include=%(fuchsia_icu_i18n)s
fuchsia-x86_64-sysroot=%(x86_64_sysroot)s
fuchsia-aarch64-sysroot=%(aarch64_sysroot)s
fuchsia-x86_64-libs=%(x64_shared)s
fuchsia-aarch64-libs=%(arm64_shared)s
host-cc=%(clang_path)s/bin/clang
host-cxx=%(clang_path)s/bin/clang++
use-lld-linker
build-swift-static-stdlib=true
build-runtime-with-host-compiler=true
build-swift-static-sdk-overlay=true
extra-cmake-options=%(extra_cmake_args)s

xctest=false
foundation=false
libdispatch=false
libicu=false
build-ninja=false

dash-dash

skip-build-foundation
skip-build-libdispatch
skip-build-xctest
skip-build-swiftpm
skip-build-lldb
skip-build-llbuild

[preset: mixin_fuchsia_release_Os]
mixin-preset=mixin_fuchsia_build

no-swift-stdlib-assertions
no-swift-assertions
no-llvm-assertions
release

dash-dash

swift-stdlib-build-type=MinSizeRel
swift-stdlib-enable-assertions=false
swift-enable-ast-verifier=0

[preset: mixin_fuchsia_release_debuginfo]
mixin-preset=mixin_fuchsia_build

no-swift-stdlib-assertions
release-debuginfo
assertions

dash-dash

swift-stdlib-build-type=RelWithDebInfo
swift-stdlib-enable-assertions=false
swift-enable-ast-verifier=0


# We will re-enable these when tests work
[preset: mixin_fuchsia_disable_testing]

dash-dash

skip-test-cmark
skip-test-lldb
skip-test-swift
skip-test-llbuild
skip-test-swiftpm
skip-test-xctest
skip-test-foundation
skip-test-libdispatch
skip-test-playgroundlogger
skip-test-playgroundsupport
skip-test-libicu
skip-test-fuchsia-host

[preset: mixin_fuchsia_install]

dash-dash

swift-install-components=autolink-driver;compiler;clang-builtin-headers;stdlib;swift-remote-mirror;sdk-overlay;license;editor-integration;tools;dev
install-swift
install-prefix=/
install-destdir=%(install_destdir)s
install-symroot=%(install_symroot)s
reconfigure

#===------------------------------------------------------------------------===#
# Fuchsia Targets
#===------------------------------------------------------------------------===#
[preset: fuchsia_release]
mixin-preset=
  mixin_fuchsia_release_Os
  mixin_fuchsia_disable_testing

[preset: fuchsia_release_debuginfo]
mixin-preset=
  mixin_fuchsia_release_debuginfo
  mixin_fuchsia_disable_testing

[preset: fuchsia_release_install]
mixin-preset=
  fuchsia_release
  mixin_fuchsia_install

[preset: fuchsia_release_debuginfo_install]
mixin-preset=
  fuchsia_release_debuginfo
  mixin_fuchsia_install


#===------------------------------------------------------------------------===#
# Linux Extra Targets
#===------------------------------------------------------------------------===#
# We build this after doing a regular build to get the additional depedencies
# for just Linux that don't work on Fuchsia yet.

[preset: linux_extras_install]
no-swift-stdlib-assertions
no-swift-assertions
no-llvm-assertions
host-cc=%(clang_path)s/bin/clang
host-cxx=%(clang_path)s/bin/clang++
use-lld-linker
build-swift-static-stdlib=true
build-runtime-with-host-compiler=true
build-swift-static-sdk-overlay=true
llbuild
swiftpm
xctest
foundation
libdispatch
release

dash-dash

build-ninja
install-swift
install-lldb
install-llbuild
install-swiftpm
install-xctest
install-foundation
install-libdispatch

swift-stdlib-build-type=MinSizeRel
swift-stdlib-enable-assertions=false
swift-enable-ast-verifier=0

skip-test-xctest
skip-test-foundation
skip-test-libdispatch
skip-test-playgroundlogger
skip-test-playgroundsupport
skip-test-libicu

swift-install-components=autolink-driver;compiler;clang-builtin-headers;stdlib;swift-remote-mirror;sdk-overlay;license;editor-integration;tools;dev;sourcekit-inproc;swift-remote-mirror-headers
llvm-install-components=libclang;libclang-headers
install-prefix=/
install-destdir=%(install_destdir)s
install-symroot=%(install_symroot)s
reconfigure

"""

# TODO(zbowling): we need to move all of these repos to checkout the
# Google github or some googlesource.com mirrors.
UPDATE_CHECKOUT_CONFIG = """
{
    "https-clone-pattern": "https://fuchsia.googlesource.com/third_party/%s",
    "ssh-clone-pattern": "git@github.com:google/%s.git",
    "repos": {
        "compiler-rt": {
            "remote": {
                "id": "swift-compiler-rt"
            }
        },
        "llvm": {
            "remote": {
                "id": "swift-llvm"
            }
        },
        "swift-corelibs-foundation": {
            "remote": {
                "id": "swift-corelibs-foundation"
            }
        },
        "clang": {
            "remote": {
                "id": "swift-clang"
            }
        },
        "llbuild": {
            "remote": {
                "id": "swift-llbuild"
            }
        },
        "cmark": {
            "remote": {
                "id": "swift-cmark"
            }
        },
        "lldb": {
            "remote": {
                "id": "swift-lldb"
            }
        },
        "swift-corelibs-xctest": {
            "remote": {
                "id": "swift-corelibs-xctest"
            }
        },
        "ninja": {
            "remote": {
                "id": "ninja"
            }
        },
        "swift-integration-tests": {
            "remote": {
                "id": "swift-integration-tests"
            }
        },
        "swiftpm": {
            "remote": {
                "id": "swift-package-manager"
            }
        },
        "swift": {
            "remote": {
                "id": "swift"
            }
        },
        "swift-corelibs-libdispatch": {
            "remote": {
                "id": "swift-corelibs-libdispatch"
            }
        }
    },
    "branch-schemes": {
        "fuchsia": {
            "repos": {
                "compiler-rt": "61fa9e3fd80fb9c2abc71e34b254c1c8b12c9c71",
                "llvm": "cf0f1343596c56da3cbf3e98900b0402248d1c61",
                "swift-corelibs-foundation": "ad2f29b446c6aba991f250500d2e6f3a8706c6fa",
                "clang": "ef223bbbebb24d836334f2712d9ca68ff265269b",
                "llbuild": "473365152503f0fce2cde3be7f7dcb9699fdca87",
                "cmark": "d875488a6a95d5487b7c675f79a8dafef210a65f",
                "lldb": "14981bfc6cb9a482e729d6411b6be1ac5d8a12e4",
                "swiftpm": "0297d83f1c991ae7e5e74fa39849b0b70b9f387f",
                "swift-corelibs-xctest": "732d9533c70dca9ede2c745b64a11f8c7dc7f824",
                "ninja": "253e94c1fa511704baeb61cf69995bbf09ba435e",
                "swift-integration-tests": "01eecd5a83279635823e78101a538132784bc628",
                "swift": "6058ffab78270a048e27047292becc847fbc0184",
                "swift-corelibs-libdispatch": "e52c174b1f1883eebad6ba7bdd54edbd4736617e"
            },
            "aliases": [
                "fuchsia"
            ]
        }
    }
}
"""


# TODO(zbowling): We are building packages for all of garnet. This is overkill.
def BuildFuchsia(api, target_cpu, fuchsia_out_dir):
  fuchsia_build_dir = fuchsia_out_dir.join('release-%s' % target_cpu)

  with api.step.nest('build fuchsia ' + target_cpu):
    gen_cmd = [
      api.path['start_dir'].join('build', 'gn', 'gen.py'),
      '--target_cpu=%s' % target_cpu,
      '--packages=garnet/packages/default',
    ]

    gen_cmd.append('--goma=%s' % api.goma.goma_dir)

    # Build Fuchsia for release.
    # In theory, we shouldn't be statically linking anything from Fuchsia.
    gen_cmd.append('--release')

    api.step('gen fuchsia', gen_cmd)

    ninja_cmd = [
      api.path['start_dir'].join('buildtools', 'ninja'),
      '-C', fuchsia_build_dir,
    ]

    ninja_cmd.extend(['-j', api.goma.recommended_goma_jobs])

    api.step('ninja', ninja_cmd)


def RunSteps(api, url, ref, revision, goma_dir):
  api.gitiles.ensure_gitiles()
  api.gsutil.ensure_gsutil()
  api.jiri.ensure_jiri()
  if goma_dir:
    api.goma.set_goma_dir(goma_dir)

  api.goma.ensure_goma()

  api.cipd.set_service_account_credentials(
     api.cipd.default_bot_service_account_credentials)

  if not revision:
    revision = api.gitiles.refs(url).get(ref, None)
  cipd_pkg_name = 'fuchsia/swift/' + api.cipd.platform_suffix()
  step = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if step.json.output['result']:
    api.step('Package is up-to-date', cmd=None)
    return

  swift_source_dir = api.path['start_dir'].join('swift-source')
  swift_dir = swift_source_dir.join('swift')
  api.file.ensure_directory('swift-source', swift_source_dir)

  with api.context(infra_steps=True):
    api.jiri.init()
    # TODO(zbowling): we are pulling in a garnet manifest now, but eventually
    # Swift will be included in the garnet manfiest itself, so we will instead
    # to pull manifest that that is just:
    # zircon + clang toolchain + third_party/icu.
    api.jiri.import_manifest(
        'manifest/garnet',
        'https://fuchsia.googlesource.com/garnet',
        'garnet'
    )
    api.jiri.update()

    api.git.checkout(url, swift_dir, ref=revision)

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      api.cipd.ensure(cipd_dir, {
          'infra/cmake/${platform}': 'version:3.9.2',
          'infra/ninja/${platform}': 'version:1.8.2',
          'fuchsia/clang/${platform}': 'latest',
      })

  # Build zircon for both x64 and arm64
  zircon_dir = api.path['start_dir'].join('zircon')
  for project in ['x64', 'arm64']:
    build_zircon_cmd = [
      api.path['start_dir'].join('scripts', 'build-zircon.sh'),
      '-H',
      '-v',
      '-p', project,
    ]
    api.step('build zircon '+ project, build_zircon_cmd)

  goma_env = {}

  fuchsia_out_dir = api.path['start_dir'].join('out')
  with api.goma.build_with_goma():
    BuildFuchsia(api, "arm64", fuchsia_out_dir)
    BuildFuchsia(api, "x64", fuchsia_out_dir)

  # build swift
  staging_dir = api.path.mkdtemp('swift')
  build_dir = staging_dir.join('build')
  swift_install_dir = build_dir.join("swift_toolchain")
  swift_symbols = build_dir.join("swift_symbols")
  api.file.ensure_directory('build', build_dir)

  zircon_dir = api.path['start_dir'].join('out', 'build-zircon')
  x86_64_sysroot = zircon_dir.join('build-user-x64', 'sysroot')
  aarch64_sysroot = zircon_dir.join('build-user-arm64', 'sysroot')
  linux_sysroot = api.path['start_dir'].join('buildtools', 'linux-x64',
   'sysroot')
  fuchia_x64_shared = fuchsia_out_dir.join('release-x64','x64-shared')
  fuchia_arm64_shared = fuchsia_out_dir.join('release-arm64','arm64-shared')
  presets_file = build_dir.join('presets.ini')
  checkout_config = build_dir.join('update-checkout.json')

  extra_cmake_args = ""
  if api.platform.name == "linux":
    extra_cmake_args = "-DCMAKE_SYSROOT=%s " % linux_sysroot
    # HACK: Swift uses pkg-config to find ICU paths so we need to override it.
    # This is not the best way to do this but it will work temporarily with
    # minimal changes to swift when a good number of features in swift are
    # disabled. Remove all of this when proper sysroot support is added to all
    # of swift's build system.
    linux_sysroot_include = linux_sysroot.join('include')
    linux_sysroot_lib = linux_sysroot.join('usr', 'lib', 'x86_64-linux-gnu')
    extra_cmake_args += "-DSWIFT_LINUX_ICU_UC_INCLUDE=%s " % \
      linux_sysroot_include
    extra_cmake_args += "-DSWIFT_LINUX_ICU_I18N_INCLUDE=%s " % \
      linux_sysroot_include
    extra_cmake_args += "-DSWIFT_LINUX_ICU_UC=%s " % \
      linux_sysroot_lib.join("libicuuc.so")
    extra_cmake_args += "-DSWIFT_LINUX_ICU_I18N=%s " % \
      linux_sysroot_lib.join("libicui18n.so")
    extra_cmake_args += "-DSWIFT_BUILD_SOURCEKIT:BOOL=false "


  env_prefixes = {'PATH': [cipd_dir, cipd_dir.join('bin')]}
  with api.context(cwd=build_dir, env_prefixes=env_prefixes):
    # Update checkout
    api.file.write_text('writing checkout config', checkout_config,
                        UPDATE_CHECKOUT_CONFIG)
    api.python(
        'checkout swift depedencies',
        swift_dir.join('utils', 'update-checkout'),
        args=[
            '--skip-repository', 'swift', # we manage the swift repo ourselves
            '--skip-repository', 'swift-xcode-playground-support', # no mirror
            '--config', checkout_config,
            '--scheme', 'fuchsia',
            '-j5', '--clone',
        ])

    # Build swift for Linux and Fuchsia targets without Linux extras
    api.file.write_text('writing build presets', presets_file, PRESET_FILE)
    api.python(
        'build swift fuchsia components',
        swift_dir.join('utils', 'build-script'),
        args=[
            '--preset-file', presets_file,
            '--jobs', api.platform.cpu_count,
            '--preset=fuchsia_release_install',
            'clang_path=%s' % cipd_dir,
            'fuchsia_icu_uc=%s' % api.path['start_dir'].join(
                "third_party", "icu", "source", "common"),
            'fuchsia_icu_i18n=%s' % api.path['start_dir'].join(
                "third_party", "icu", "source", "i18n"),
            'x86_64_sysroot=%s' % x86_64_sysroot,
            'aarch64_sysroot=%s' % aarch64_sysroot,
            'x64_shared=%s' % fuchia_x64_shared,
            'arm64_shared=%s' % fuchia_arm64_shared,
            'install_destdir=%s' % swift_install_dir,
            'install_symroot=%s' % swift_symbols,
            'extra_cmake_args=%s' % extra_cmake_args,
        ])

    # TODO: temporarly disabling the second phase compile for Linux until
    # all depedencies have been updated to understand how to be compiled with a
    # passed in sysroot.

    # HACK: Build swift again but with extras for Linux that do not work on
    # on Fuchsia yet (swiftpm, libdispatch, foundation, etc)
    #api.python(
    #    'build swift linux extras',
    #    swift_dir.join('utils', 'build-script'),
    #    args=[
    #        '--preset-file', presets_file,
    #        '--jobs', api.platform.cpu_count,
    #        '--preset=linux_extras_install',
    #        'clang_path=%s' % cipd_dir,
    #        'fuchsia_icu_uc=%s' % api.path['start_dir'].join(
    #            "third_party", "icu", "source", "common"),
    #        'fuchsia_icu_i18n=%s' % api.path['start_dir'].join(
    #            "third_party", "icu", "source", "i18n"),
    #        'x86_64_sysroot=%s' % x86_64_sysroot,
    #        'aarch64_sysroot=%s' % aarch64_sysroot,
    #        'x64_shared=%s' % fuchia_x64_shared,
    #        'arm64_shared=%s' % fuchia_arm64_shared,
    #        'install_destdir=%s' % swift_install_dir,
    #        'install_symroot=%s' % swift_symbols,
    #    ])


  # TODO(zbowling): remove this in favor of doing it similar to the way
  # clang_path does it below.
  swift_install_lib = swift_install_dir.join('lib','swift','fuchsia')
  api.file.write_text('writing x86_64 manifest',
      swift_install_lib.join("x86_64","toolchain.manifest"), MANIFEST_FILE)
  api.file.write_text('writing aarch64 manifest',
      swift_install_lib.join("aarch64", "toolchain.manifest"), MANIFEST_FILE)

  install_lib = swift_install_dir.join('lib')
  api.file.write_text('writing x86_64 manifest',
      install_lib.join("x86_64-fuchsia.manifest"), MANIFEST_FILE)
  api.file.write_text('writing aarch64 manifest',
      install_lib.join("aarch64-fuchsia.manfiest"), MANIFEST_FILE)


  cipd_pkg_file = staging_dir.join('swift.cipd')

  step_result = api.step(
      'swift version', [swift_install_dir.join('bin', 'swift'), '--version'],
      stdout=api.raw_io.output())
  m = re.search(r'version ([0-9a-z.-]+)', step_result.stdout)
  assert m, 'Cannot determine Swift version'
  swift_version = m.group(1)

  api.cipd.build(
      input_dir=swift_install_dir,
      package_name=cipd_pkg_name,
      output_package=cipd_pkg_file,
      install_mode='copy',
  )
  step_result = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'version': swift_version,
          'git_repository': SWIFT_FUCHSIA_GIT,
          'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join('swift', api.cipd.platform_suffix(),
                      step_result.json.output['result']['instance_id']),
      unauthenticated_url=True)


def GenTests(api):
  revision = '85bce8d910db00261b4844f784dca1a8e322b7e0'
  version = "Swift version 4.1-dev (LLVM 7959c1098f, Clang dff0a814ae, Swift 6058ffab78)"

  for platform in ('linux','mac'):
    yield (api.test(platform + "_existing") +
           api.platform.name(platform) +
           api.properties(goma_dir='/goma') +
           api.gitiles.refs('refs', ('refs/heads/upstream/fuchsia_release', revision)) +
           api.step_data('cipd search fuchsia/swift/' + platform + '-amd64 ' +
                         'git_revision:' + revision, api.json.output({
                             'result': ["something"]
                         })))
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/upstream/fuchsia_release', revision)) +
           api.step_data('swift version', api.raw_io.stream_output(version)) +
           api.step_data('cipd search fuchsia/swift/' + platform + '-amd64 ' +
                         'git_revision:' + revision, api.json.output({
                             'result': []
                         })))
