# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'go',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]


def RunSteps(api):
  # First, you need a go distribution.
  api.go.ensure_go()
  api.go.ensure_go(version='go_version:1.6')
  assert api.go.go_root
  assert api.go.go_executable

  # Build a go package.
  api.go('build', 'fuchsia.googlesource.com/foo')

  # Test a go package.
  api.go('test', 'fuchsia.googlesource.com/foo')

  # Run a go program.
  input = api.raw_io.input("""package main

import "fmt"

func main() {
	fmt.Printf("Hello, world.\n")
}""", '.go')

  api.go('run', input)

  # Run an inline go program.
  api.go.inline("""package main

import "fmt"

func main() {
	fmt.Printf("Hello, world.\n")
}""")


def GenTests(api):
  yield (
      api.test('basic') +
      api.platform('linux', 64)
  )
