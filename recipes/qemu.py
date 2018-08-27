# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building QEMU."""

from recipe_engine.config import Enum, ReturnSchema, Single
from recipe_engine.recipe_api import Property


DEPS = [
  'infra/git',
  'infra/gitiles',
  'infra/goma',
  'infra/gsutil',
  'recipe_engine/cipd',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/tempfile',
]

PLATFORM_TO_TRIPLE = {
  'linux-amd64': 'x86_64-linux-gnu',
  'linux-arm64': 'aarch64-linux-gnu',
  'mac-amd64': 'x86_64-apple-darwin',
}
PLATFORMS = PLATFORM_TO_TRIPLE.keys()

PROPERTIES = {
  'repository':
      Property(
          kind=str, help='Git repository URL',
          default='https://fuchsia.googlesource.com/third_party/qemu'),
  'branch':
      Property(kind=str, help='Git branch', default='refs/heads/master'),
  'revision':
      Property(kind=str, help='Revision', default=None),
  'platform':
      Property(
          kind=str, help='CIPD platform for the target', default=None),
}


def platform_sysroot(api, cipd_dir, platform):
  if platform.startswith('linux'):
    return cipd_dir.join('sysroot')
  elif platform.startswith('mac'): # pragma: no cover
    # TODO(IN-148): Eventually use our own hermetic sysroot as for Linux.
    step_result = api.step(
        'xcrun', ['xcrun', '--show-sdk-path'],
        stdout=api.raw_io.output(name='sdk-path', add_output_log=True),
        step_test_data=lambda: api.raw_io.test_api.stream_output(
            '/some/xcode/path'))
    return step_result.stdout.strip()


def configure(api, cipd_dir, src_dir, platform, host, flags=[], step_name='configure'):
  target = PLATFORM_TO_TRIPLE[platform]
  sysroot = platform_sysroot(api, cipd_dir, platform)

  variables = {
    'CC': cipd_dir.join('bin', 'clang'),
    'CXX': cipd_dir.join('bin', 'clang++'),
    'CFLAGS': '--target=%s --sysroot=%s' % (target, sysroot),
    'CXXFLAGS': '--target=%s --sysroot=%s' % (target, sysroot),
    'LDFLAGS': '--target=%s --sysroot=%s' % (target, sysroot),
  }
  if platform.startswith('linux'):
    variables.update({
      'AR': cipd_dir.join('bin', 'llvm-ar'),
      'RANLIB': cipd_dir.join('bin', 'llvm-ranlib'),
      'NM': cipd_dir.join('bin', 'llvm-nm'),
      'STRIP': cipd_dir.join('bin', 'llvm-strip'),
      'OBJCOPY': cipd_dir.join('bin', 'llvm-objcopy'),
    })

  return api.step(step_name, [
    src_dir.join('configure'),
    '--build=%s' % PLATFORM_TO_TRIPLE[host],
    '--host=%s' % target,
  ] + flags + ['%s=%s' % (k, v) for k, v in variables.iteritems()])


def cmake(api, cipd_dir, src_dir, platform, options=[], step_name='cmake'):
  if platform.startswith('linux'):
    options.extend([
      '-DCMAKE_LINKER=%s' % cipd_dir.join('bin', 'ld.lld'),
      '-DCMAKE_NM=%s' % cipd_dir.join('bin', 'llvm-nm'),
      '-DCMAKE_OBJCOPY=%s' % cipd_dir.join('bin', 'llvm-objcopy'),
      '-DCMAKE_OBJDUMP=%s' % cipd_dir.join('bin', 'llvm-objdump'),
      '-DCMAKE_RANLIB=%s' % cipd_dir.join('bin', 'llvm-ranlib'),
      '-DCMAKE_STRIP=%s' % cipd_dir.join('bin', 'llvm-strip'),
    ])

  target = PLATFORM_TO_TRIPLE[platform]
  return api.step(step_name, [
    cipd_dir.join('bin', 'cmake'),
    '-GNinja',
    '-DCMAKE_MAKE_PROGRAM=%s' % cipd_dir.join('ninja'),
    '-DCMAKE_C_COMPILER=%s' % cipd_dir.join('bin', 'clang'),
    '-DCMAKE_C_COMPILER_TARGET=%s' % target,
    '-DCMAKE_CXX_COMPILER=%s' % cipd_dir.join('bin', 'clang++'),
    '-DCMAKE_CXX_COMPILER_TARGET=%s' % target,
    '-DCMAKE_SYSROOT=%s' % platform_sysroot(api, cipd_dir, platform),
  ] + options + [
    src_dir
  ])


def upload_package(api, pkg_name, pkg_dir, repository, revision):
  cipd_pkg_name = 'fuchsia/' + pkg_name
  pkg_def = api.cipd.PackageDefinition(
      package_name=cipd_pkg_name,
      package_root=pkg_dir,
      install_mode='copy')
  pkg_def.add_dir(pkg_dir)
  pkg_def.add_version_file('.versions/%s.cipd_version' % cipd_pkg_name)

  cipd_pkg_file = api.path['cleanup'].join(pkg_name.replace('/', '_') + '.cipd')
  api.cipd.build_from_pkg(
      pkg_def=pkg_def,
      output_package=cipd_pkg_file,
  )

  cipd_pins = api.cipd.search(cipd_pkg_name, 'git_revision:' + revision)
  if cipd_pins:
    api.step('Package is up-to-date', cmd=None)
    return

  cipd_pin = api.cipd.register(
      package_name=cipd_pkg_name,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
        'git_repository': repository,
        'git_revision': revision,
      },
  )

  api.gsutil.upload(
      'fuchsia',
      cipd_pkg_file,
      api.gsutil.join(pkg_name, cipd_pin.instance_id),
      unauthenticated_url=True
  )


def build_zlib(api, cipd_dir, pkg_dir, platform):
  src_dir = api.path.mkdtemp('zlib_src')
  api.git.checkout('https://fuchsia.googlesource.com/third_party/zlib',
                   src_dir, 'v1.2.11', submodules=False)
  build_dir = api.path.mkdtemp('zlib_build')

  with api.context(cwd=build_dir):
    cmake(api, cipd_dir, src_dir, platform, [
      '-DCMAKE_INSTALL_PREFIX=',
      '-DCMAKE_BUILD_TYPE=Release',
      '-DBUILD_SHARED_LIBS=OFF',
    ])
    api.step('build', [cipd_dir.join('ninja')])
    with api.context(env={'DESTDIR': pkg_dir}):
      api.step('install', [cipd_dir.join('ninja'), 'install'])


def build_pixman(api, cipd_dir, pkg_dir, platform, host):
  src_dir = api.path.mkdtemp('pixman_src')
  api.git.checkout('https://fuchsia.googlesource.com/third_party/pixman',
                   src_dir, ref='upstream/master', submodules=False)
  build_dir = api.path.mkdtemp('pixman_build')

  with api.context(cwd=src_dir, env={'NOCONFIGURE': '1'}):
    api.step('autogen', [src_dir.join('autogen.sh')])
  with api.context(cwd=build_dir):
    configure(api, cipd_dir, src_dir, platform, host, [
      '--prefix=',
      '--enable-static',
      '--disable-shared',
      '--with-pic',
    ])
    api.step('build', ['make', '-j%d' % api.goma.jobs])
    api.step('install', ['make', 'install', 'DESTDIR=%s' % pkg_dir])


def build_sdl(api, cipd_dir, pkg_dir, platform, env={}):
  src_dir = api.path.mkdtemp('sdl_src')
  api.git.checkout('https://fuchsia.googlesource.com/third_party/sdl',
                   src_dir, ref='refs/tags/release-2.0.5', submodules=False)
  build_dir = api.path.mkdtemp('sdl_build')

  with api.context(cwd=build_dir):
    cmake(api, cipd_dir, src_dir, platform, [
      '-DCMAKE_INSTALL_PREFIX=',
      '-DVIDEO_WAYLAND=OFF',
      '-DSDL_SHARED=OFF',
      '-DSDL_STATIC_PIC=ON',
      '-DGCC_ATOMICS=ON',
    ])
    api.step('build', [cipd_dir.join('ninja')])
    with api.context(env={'DESTDIR': pkg_dir}):
      api.step('install', [cipd_dir.join('ninja'), 'install'])


def build_libffi(api, cipd_dir, pkg_dir, platform, host):
  src_dir = api.path.mkdtemp('libffi_src')
  api.git.checkout('https://fuchsia.googlesource.com/third_party/libffi',
                   src_dir, ref='refs/tags/v3.3-rc0', submodules=False)
  build_dir = api.path.mkdtemp('libffi_build')

  with api.context(cwd=src_dir):
    api.step('autogen', [src_dir.join('autogen.sh')])
  with api.context(cwd=build_dir):
    configure(api, cipd_dir, src_dir, platform, host, [
      '--prefix=',
      '--target=%s' % PLATFORM_TO_TRIPLE[platform],
      '--with-pic',
      '--enable-static',
      '--disable-shared',
    ])
    api.step('build', ['make', '-j%d' % api.goma.jobs])
    api.step('install', ['make', 'install', 'DESTDIR=%s' % pkg_dir])


def build_gettext(api, cipd_dir, pkg_dir, platform, host):
  src_dir = api.path.mkdtemp('gettext_src')
  api.git.checkout('https://fuchsia.googlesource.com/third_party/gettext',
                   src_dir, submodules=True)
  build_dir = api.path.mkdtemp('gettext_build')

  with api.context(cwd=src_dir):
    api.step('autogen', [src_dir.join('autogen.sh')])
  with api.context(cwd=build_dir):
    configure(api, cipd_dir, src_dir, platform, host, [
      '--prefix=',
      '--target=%s' % PLATFORM_TO_TRIPLE[platform],
      '--with-pic',
      '--enable-static',
      '--disable-shared',
      '--disable-nls',
    ])
    api.step('build', ['make', '-j%d' % api.goma.jobs])
    api.step('install', ['make', 'install', 'DESTDIR=%s' % pkg_dir])


def build_glib(api, cipd_dir, pkg_dir, platform, host):
  src_dir = api.path.mkdtemp('glib_src')
  api.git.checkout('https://fuchsia.googlesource.com/third_party/glib',
                   src_dir, ref='refs/tags/2.57.2', submodules=False)
  build_dir = api.path.mkdtemp('glib_build')

  with api.context(cwd=src_dir, env={'NOCONFIGURE': '1'}):
    api.step('autogen', [src_dir.join('autogen.sh')])
  with api.context(cwd=build_dir):
    configure(api, cipd_dir, src_dir, platform, host, [
      '--prefix=',
      '--with-pic',
      '--with-pcre=internal',
      '--enable-static',
      '--disable-dtrace',
      '--disable-libelf',
      '--disable-libmount',
      '--disable-shared',
    ])
    api.step('build', ['make', '-j%d' % api.goma.jobs])
    api.step('install', ['make', 'install', 'DESTDIR=%s' % pkg_dir])


def build_qemu(api, cipd_dir, pkg_dir, platform, host):
  src_dir = api.path.mkdtemp('qemu_src')
  repository = 'https://fuchsia.googlesource.com/third_party/qemu'
  revision = api.git.checkout(repository, src_dir, submodules=True)
  build_dir = api.path.mkdtemp('qemu_build')
  install_dir = api.path.mkdtemp('qemu_install')

  target = PLATFORM_TO_TRIPLE[platform]

  extra_options = {
    'linux': [
      '--cc=%s' % cipd_dir.join('bin', 'clang'),
      '--cxx=%s' % cipd_dir.join('bin', 'clang++'),
      '--build=%s' % PLATFORM_TO_TRIPLE[host],
      '--host=%s' % target,
      '--extra-cflags=--target=%s --sysroot=%s' % (target, cipd_dir.join('sysroot')),
      '--extra-cxxflags=--target=%s --sysroot=%s' % (target, cipd_dir.join('sysroot')),
      # Supress warning about the unused arguments because QEMU ignores
      # --disable-werror at configure time which triggers an error because
      # -static-libstdc++ is unused when linking C code.
      '--extra-ldflags=--target=%s --sysroot=%s -static-libstdc++ -Qunused-arguments -ldl -lpthread' % (target, cipd_dir.join('sysroot')),
      '--disable-gtk',
      '--disable-x11',
      '--enable-sdl',
      '--enable-kvm',
    ],
    'mac': [
      '--enable-cocoa',
    ],
  }[platform.split('-')[0]]

  with api.context(cwd=build_dir):
    api.step('configure qemu', [
      src_dir.join('configure'),
      '--prefix=',
      '--target-list=aarch64-softmmu,x86_64-softmmu',
      '--without-system-fdt',
      '--disable-attr',
      '--disable-bluez',
      '--disable-brlapi',
      '--disable-bzip2',
      '--disable-cap-ng',
      '--disable-curl',
      '--disable-curses',
      '--disable-debug-info',
      '--disable-debug-tcg',
      '--disable-docs',
      '--disable-gcrypt',
      '--disable-glusterfs',
      '--disable-gnutls',
      '--disable-guest-agent',
      '--disable-libiscsi',
      '--disable-libnfs',
      '--disable-libssh2',
      '--disable-libusb',
      '--disable-libxml2',
      '--disable-linux-aio',
      '--disable-lzo',
      '--disable-nettle',
      '--disable-opengl',
      '--disable-qom-cast-debug',
      '--disable-rbd',
      '--disable-rdma',
      '--disable-seccomp',
      '--disable-smartcard',
      '--disable-snappy',
      '--disable-spice',
      '--disable-tasn1',
      '--disable-tcg-interpreter',
      '--disable-tcmalloc',
      '--disable-tpm',
      '--disable-usb-redir',
      '--disable-vhost-scsi',
      '--disable-vhost-vsock',
      '--disable-virtfs',
      '--disable-vnc-jpeg',
      '--disable-vnc-png',
      '--disable-vnc-sasl',
      '--disable-vte',
      '--disable-werror',
      '--disable-xen',
    ] + extra_options)
    api.step('build', ['make', '-j%d' % api.platform.cpu_count])
    api.step('install', ['make', 'install', 'DESTDIR=%s' % install_dir])

  qemu_version = api.file.read_text('version', src_dir.join('VERSION'),
                                    test_data='2.10.1')
  assert qemu_version, 'Cannot determine QEMU version'

  upload_package(api, 'third_party/qemu/' + platform, install_dir, repository, revision)


def RunSteps(api, repository, branch, revision, platform):
  api.gitiles.ensure_gitiles()
  api.goma.ensure_goma()
  api.gsutil.ensure_gsutil()

  if not revision:
    revision = api.gitiles.refs(repository).get(branch, None)

  # TODO: factor this out into a host_build recipe module.
  host_platform = '%s-%s' % (api.platform.name.replace('win', 'windows'), {
      'intel': {
          32: '386',
          64: 'amd64',
      },
      'arm': {
          32: 'armv6',
          64: 'arm64',
      },
  }[api.platform.arch][api.platform.bits])
  target_platform = platform or host_platform

  with api.step.nest('ensure_packages'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')
      pkgs = api.cipd.EnsureFile()
      pkgs.add_package('infra/cmake/${platform}', 'version:3.9.2')
      pkgs.add_package('infra/ninja/${platform}', 'version:1.8.2')
      pkgs.add_package('fuchsia/clang/${platform}', 'goma')
      if target_platform.startswith('linux'):
        pkgs.add_package('fuchsia/sysroot/%s' % target_platform, 'latest', 'sysroot')
      api.cipd.ensure(cipd_dir, pkgs)

  pkg_dir = api.path['start_dir'].join('pkgconfig')
  api.file.ensure_directory('create pkg dir', pkg_dir)

  target = PLATFORM_TO_TRIPLE[target_platform]

  env = {
    'PKG_CONFIG_SYSROOT_DIR': pkg_dir,
    'PKG_CONFIG_ALLOW_SYSTEM_CFLAGS': 1,
    'PKG_CONFIG_ALLOW_SYSTEM_LIBS': 1,
    'PKG_CONFIG_LIBDIR': ':'.join([str(pkg_dir.join('share', 'pkgconfig')),
                                   str(pkg_dir.join('lib', 'pkgconfig'))]),
  }

  with api.context(env=env):
    if target_platform.startswith('linux'):
      with api.step.nest('sdl'):
        build_sdl(api, cipd_dir, pkg_dir, target_platform)

    with api.step.nest('zlib'):
      build_zlib(api, cipd_dir, pkg_dir, target_platform)

    with api.step.nest('pixman'):
      build_pixman(api, cipd_dir, pkg_dir, target_platform, host_platform)

    with api.step.nest('libffi'):
      build_libffi(api, cipd_dir, pkg_dir, target_platform, host_platform)

    with api.step.nest('gettext'):
      build_gettext(api, cipd_dir, pkg_dir, target_platform, host_platform)

    with api.step.nest('glib'):
      build_glib(api, cipd_dir, pkg_dir, target_platform, host_platform)

    with api.step.nest('qemu'):
      build_qemu(api, cipd_dir, pkg_dir, target_platform, host_platform)


def GenTests(api):
  revision = '75b05681239cb309a23fcb4f8864f177e5aa62da'
  version = 'QEMU emulator version 2.8.0 (v2.8.0-15-g28cd8b6577-dirty)'
  for platform in ['linux', 'mac']:
    yield (api.test(platform) +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.properties(manifest='qemu',
                          remote='https://fuchsia.googlesource.com/manifest',
                          platform=platform + '-amd64') +
           api.step_data('qemu.version', api.raw_io.stream_output(version)))
    yield (api.test(platform + '_new') +
           api.platform.name(platform) +
           api.gitiles.refs('refs', ('refs/heads/master', revision)) +
           api.properties(manifest='qemu',
                          remote='https://fuchsia.googlesource.com/manifest',
                          platform=platform + '-amd64') +
           api.step_data('qemu.version', api.raw_io.stream_output(version)) +
           api.step_data('qemu.cipd search fuchsia/third_party/qemu/' + platform + '-amd64 ' +
                         'git_revision:deadbeef',
                         api.cipd.example_search('fuchsia/qemu/' + platform + '-amd64 ', [])))
  yield (api.test('linux_arm64') +
         api.platform.name('linux') +
         api.gitiles.refs('refs', ('refs/heads/master', revision)) +
         api.properties(manifest='qemu',
                        remote='https://fuchsia.googlesource.com/manifest',
                        platform='linux-arm64') +
         api.step_data('qemu.version', api.raw_io.stream_output(version)))
