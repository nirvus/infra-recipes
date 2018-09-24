# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Recipe for rolling chromium prebuilts into Fuchsia."""

import re

from recipe_engine.config import Enum, Single
from recipe_engine.recipe_api import Property

DEPS = [
    'infra/auto_roller',
    'infra/git',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = {
    'dry_run':
        Property(
            kind=bool,
            default=False,
            help=
            'Whether to dry-run the auto-roller (CQ+1 and abandon the change)'),
}

COMMIT_MESSAGE = """[roll] Roll chromium {version}

Test: CQ
"""

def GetVersionsFromCIPD(api, cipd_pkg):
    return set([
        getattr(tag, 'tag')
        for tag in getattr(
            api.cipd.describe(cipd_pkg, 'latest'), 'tags')
        if getattr(tag, 'tag').startswith('version:')
    ])

def RunSteps(api, dry_run):
  topaz_path = api.path['start_dir'].join('topaz')

  with api.context(infra_steps=True):
    api.git.checkout(
        url='https://fuchsia.googlesource.com/topaz',
        path=topaz_path,
        ref='master',
    )

    chromium_cipd_pkgs = [
        'chromium/fuchsia/webrunner-arm64',
        'chromium/fuchsia/webrunner-amd64',
        'chromium/fuchsia/fidl'
    ]

    # Populate the set of versions
    versions = GetVersionsFromCIPD(api, chromium_cipd_pkgs[0])

    # Get the intersection of all 'version' tags
    for cipd_pkg in chromium_cipd_pkgs[1:]:
      versions = versions.intersection(GetVersionsFromCIPD(api, cipd_pkg))

    # Check if the intersection of 'version' tags exists
    if not versions:
      return

    # All the 'version' tags point to the same 'instance_id'
    # Take the first 'version'
    version = list(versions)[0]
    pins = dict()
    # Query CIPD for the Pin for each 'version' and extract the 'instance_id'
    for cipd_pkg in chromium_cipd_pkgs:
        pins[cipd_pkg] = getattr(
            api.cipd.search(cipd_pkg, version)[0], 'instance_id')

    ensure_file = topaz_path.join('tools', 'cipd.ensure')
    ensure_contents = api.file.read_text(
        name='read cipd.ensure', source=ensure_file)

    # Replace the CIPD instance_id for each package
    for cipd_pkg in chromium_cipd_pkgs:
        with api.step.nest('update %s' % cipd_pkg):
            pattern = re.compile(
                re.escape(cipd_pkg) + r' [A-Za-z0-9_\-]+', re.MULTILINE)
            repl = cipd_pkg + ' ' + pins[cipd_pkg]
            ensure_contents = re.sub(pattern, repl, ensure_contents)

    api.file.write_text(
        name='write cipd.ensure',
        dest=ensure_file,
        text_data=ensure_contents)

    # Update //topaz/runtime/chromium/chromium_web_sources.gni
    update_web_sources_path = topaz_path.join(
        'runtime', 'chromium', 'update_chromium_web_sources.py')
    api.step('update chromium_websources.gni', [update_web_sources_path])

    message = COMMIT_MESSAGE.format(version=version)

    # Land the changes.
    api.auto_roller.attempt_roll(
        gerrit_project='https://fuchsia-review.googlesource.com/topaz',
        repo_dir=topaz_path,
        commit_message=message,
        dry_run=dry_run,
    )


ENSURE_FILE_TEST = """
# Chromium fidl
@Subdir third_party/chromium/fidl/chromium.web
chromium/fuchsia/fidl EOsmhnsgGIcps05Hs4hEf9-BHp4z8pATEdrheLPYUKsC

# Chromium amd64 / x64 implementation
@Subdir third_party/chromium/arch/x64
chromium/fuchsia/webrunner-amd64 3vLSLn5TGO2xs9yJsrFKu_zV6ymZUsSf9vsoKia8hLYC

# Chromium arm64 / aarch64 implementation
@Subdir third_party/chromium/arch/arm64
chromium/fuchsia/webrunner-arm64 MJ7UtEYtf-TrPBUAQ_xM0MKgzxM4ZAwYas-Uw-AfGW4C
"""


def GenTests(api):
  yield api.test('default') + api.step_data(
      'cipd describe chromium/fuchsia/fidl',
      api.json.output({
          "result": {
              "pin": {
                  "package": "chromium/fuchsia/fidl",
                  "instance_id": "GDGGW7Xs89z2apGaYf1mDvbQuHfYIoPexfedNzvKodUC"
              },
              "registered_by":
                  "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
              "registered_ts":
                  1537235671,
              "refs": [{
                  "ref":
                      "latest",
                  "instance_id":
                      "GDGGW7Xs89z2apGaYf1mDvbQuHfYIoPexfedNzvKodUC",
                  "modified_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "modified_ts":
                      1537667650
              }],
              "tags": [{
                  "tag":
                      "version:70.0.3538.30",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537667650
              }, {
                  "tag":
                      "version:70.0.3538.29",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537581345
              }, {
                  "tag":
                      "version:70.0.3538.28",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537494981
              }, {
                  "tag":
                      "version:70.0.3538.27",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537410782
              }, {
                  "tag":
                      "version:70.0.3538.25",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537322098
              }, {
                  "tag":
                      "version:70.0.3538.22",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537235671
              }]
          }
      }),
  ) + api.step_data(
      'cipd describe chromium/fuchsia/webrunner-amd64',
      api.json.output({
          "result": {
              "pin": {
                  "package": "chromium/fuchsia/webrunner-amd64",
                  "instance_id": "r2S5xldLzzfJa2VzOYgoC6TsIWePSDLBI5FRywd_gHAC"
              },
              "registered_by":
                  "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
              "registered_ts":
                  1537667675,
              "refs": [{
                  "ref":
                      "latest",
                  "instance_id":
                      "r2S5xldLzzfJa2VzOYgoC6TsIWePSDLBI5FRywd_gHAC",
                  "modified_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "modified_ts":
                      1537667675
              }],
              "tags": [{
                  "tag":
                      "version:70.0.3538.30",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537667675
              }]
          }
      }),
  ) + api.step_data(
      'cipd describe chromium/fuchsia/webrunner-arm64',
      api.json.output({
          "result": {
              "pin": {
                  "package": "chromium/fuchsia/webrunner-arm64",
                  "instance_id": "mKI1nni0SW4F1cQAuYnkYU_RtDv47noSKO9vGHJVjzYC"
              },
              "registered_by":
                  "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
              "registered_ts":
                  1537667742,
              "refs": [{
                  "ref":
                      "latest",
                  "instance_id":
                      "mKI1nni0SW4F1cQAuYnkYU_RtDv47noSKO9vGHJVjzYC",
                  "modified_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "modified_ts":
                      1537667742
              }],
              "tags": [{
                  "tag":
                      "version:70.0.3538.30",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537667742
              }]
          }
      }),
  ) + api.step_data(
      'cipd search chromium/fuchsia/webrunner-arm64 version:70.0.3538.30',
      api.json.output({
          "result": [{
              "package": "chromium/fuchsia/webrunner-arm64",
              "instance_id": "mKI1nni0SW4F1cQAuYnkYU_RtDv47noSKO9vGHJVjzYC"
          }]
      }),
  ) + api.step_data(
      'cipd search chromium/fuchsia/webrunner-amd64 version:70.0.3538.30',
      api.json.output({
          "result": [{
              "package": "chromium/fuchsia/webrunner-amd64",
              "instance_id": "r2S5xldLzzfJa2VzOYgoC6TsIWePSDLBI5FRywd_gHAC"
          }]
      }),
  ) + api.step_data(
      'cipd search chromium/fuchsia/fidl version:70.0.3538.30',
      api.json.output({
          "result": [{
              "package": "chromium/fuchsia/fidl",
              "instance_id": "GDGGW7Xs89z2apGaYf1mDvbQuHfYIoPexfedNzvKodUC"
          }]
      }),
  ) + api.step_data(
      'read cipd.ensure',
      api.raw_io.output_text(ENSURE_FILE_TEST),
  ) + api.step_data('check if done (0)', api.auto_roller.dry_run())

  yield api.test('no latest version match') + api.step_data(
      'cipd describe chromium/fuchsia/fidl',
      api.json.output({
          "result": {
              "pin": {
                  "package": "chromium/fuchsia/fidl",
                  "instance_id": "GDGGW7Xs89z2apGaYf1mDvbQuHfYIoPexfedNzvKodUC"
              },
              "registered_by":
                  "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
              "registered_ts":
                  1537235671,
              "refs": [{
                  "ref":
                      "latest",
                  "instance_id":
                      "GDGGW7Xs89z2apGaYf1mDvbQuHfYIoPexfedNzvKodUC",
                  "modified_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "modified_ts":
                      1537667650
              }],
              "tags": [{
                  "tag":
                      "version:70.0.3538.30",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537667650
              }]
          }
      }),
  ) + api.step_data(
      'cipd describe chromium/fuchsia/webrunner-amd64',
      api.json.output({
          "result": {
              "pin": {
                  "package": "chromium/fuchsia/webrunner-amd64",
                  "instance_id": "r2S5xldLzzfJa2VzOYgoC6TsIWePSDLBI5FRywd_gHAC"
              },
              "registered_by":
                  "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
              "registered_ts":
                  1537667675,
              "refs": [{
                  "ref":
                      "latest",
                  "instance_id":
                      "r2S5xldLzzfJa2VzOYgoC6TsIWePSDLBI5FRywd_gHAC",
                  "modified_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "modified_ts":
                      1537667675
              }],
              "tags": [{
                  "tag":
                      "version:70.0.3538.30",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537667675
              }]
          }
      }),
  ) + api.step_data(
      'cipd describe chromium/fuchsia/webrunner-arm64',
      api.json.output({
          "result": {
              "pin": {
                  "package": "chromium/fuchsia/webrunner-arm64",
                  "instance_id": "mKI1nni0SW4F1cQAuYnkYU_RtDv47noSKO9vGHJVjzYC"
              },
              "registered_by":
                  "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
              "registered_ts":
                  1537667742,
              "refs": [{
                  "ref":
                      "latest",
                  "instance_id":
                      "mKI1nni0SW4F1cQAuYnkYU_RtDv47noSKO9vGHJVjzYC",
                  "modified_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "modified_ts":
                      1537667742
              }],
              "tags": [{
                  "tag":
                      "version:70.0.3538.29",
                  "registered_by":
                      "user:official-cipd-upload@chops-service-accounts.iam.gserviceaccount.com",
                  "registered_ts":
                      1537667742
              }]
          }
      }),
  )
