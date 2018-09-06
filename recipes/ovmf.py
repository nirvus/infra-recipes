# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for building OVMF firmware and uploading them to CIPD.

The Open Virtual Machine Firmware (OVMF) project supports firmware for Virtual
Machines (e.g., QEMU). The produced OVMF_CODE.fd and OVMF_VARS.fd are used to
emulate EFI bootloading in QEMU in order to boot Zircon off of disk. Currently
this is only supported for x64.
"""

DEPS = [
    'infra/cipd',
    'infra/git',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

CIPD_PKG_NAME = 'fuchsia/firmware/ovmf/firmware'

# Note that this recipe accepts no properties because the recipe itself is quite
# specific, and its required configuration is encoded entirely in the logic.
PROPERTIES = {}


def RunSteps(api):
  edk2_repo = 'https://fuchsia.googlesource.com/third_party/edk2'
  checkout_dir = api.path['start_dir'].join('edk2')
  api.git.checkout(edk2_repo, checkout_dir)
  with api.context(cwd=checkout_dir):
    # Check if a CIPD upload already exists at this revision.
    revision = api.git.get_hash()
    step = api.cipd.search(CIPD_PKG_NAME, 'git_revision:%s' % revision)
    if step.json.output['result']:
      return

    # BaseTools binary is needed to build OVMF
    api.step('build BaseTools', ['make', '-C', 'BaseTools'])
    api.step('build OVMF binaries',
             ['./OvmfPkg/build.sh', '--arch=X64', '--buildtarget=RELEASE'])

  ovmf_bin_dir = checkout_dir.join('Build', 'OvmfX64', 'RELEASE_GCC5', 'FV')
  cipd_pkg_file = api.path['cleanup'].join('ovmf.cipd')
  api.cipd.build(
      input_dir=ovmf_bin_dir,
      package_name=CIPD_PKG_NAME,
      output_package=cipd_pkg_file,
      install_mode='copy',
  )
  step_result = api.cipd.register(
      package_name=CIPD_PKG_NAME,
      package_path=cipd_pkg_file,
      refs=['latest'],
      tags={
          'git_repository': edk2_repo,
          'git_revision': revision,
      },
  )


def GenTests(api):
  revision = 'abc123'
  revision_data = api.step_data('git show', api.raw_io.stream_output(revision))

  yield (api.test('not yet built for current revision') + revision_data +
         api.step_data(
             'cipd search %s ' % CIPD_PKG_NAME +
             'git_revision:%s' % revision, api.json.output({
                 'result': []
             })))
  yield (
      api.test('already built for current revision') + revision_data +
      api.step_data(
          'cipd search %s ' % CIPD_PKG_NAME +
          'git_revision:%s' % revision, api.json.output({
              'result': ['latest']
          })))
