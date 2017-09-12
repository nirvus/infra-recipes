# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'jiri',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]


def RunSteps(api):
  # First, ensure we have jiri.
  api.jiri.ensure_jiri()
  assert api.jiri.jiri

  api.jiri.checkout(
      'minimal', 'https://fuchsia.googlesource.com',
      'refs/changes/1/2/3', 'https://fuchsia-review.googlesource.com')

  # Setup a new jiri root.
  api.jiri.init('dir')

  # Import the manifest.
  api.jiri.import_manifest('minimal', 'https://fuchsia.googlesource.com',
                           overwrite=True)

  # Download all projects.
  api.jiri.update(gc=True, snapshot='snapshot', local_manifest=True)

  # Run hooks separately.
  api.jiri.update(run_hooks=False)
  api.jiri.run_hooks(local_manifest=True)

  # Take a snapshot.
  api.jiri.snapshot()

  # Emit source manifest.
  api.jiri.source_manifest()

  # Get information about the project.
  api.jiri.project(['test'])

  # Patch in an existing change.
  api.jiri.patch('refs/changes/1/2/3',
                 host='https://fuchsia-review.googlesource.com',
                 delete=True, force=True)

  # Clean up after ourselves.
  api.jiri.clean(all=True)


def GenTests(api):
  yield api.test('basic')
