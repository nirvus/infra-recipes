# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class HashApi(recipe_api.RecipeApi):
  """HashApi provides file hashing functionality."""

  def __call__(self, name, source, algorithm, test_data=''):
    self.m.path.assert_absolute(source)
    assert algorithm in ['md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512']
    step_test_data=lambda: self.test_api(test_data)
    result = self.m.python(
      name,
      self.resource('hashutil.py'),
      args=['-a', algorithm, source],
      stdout=self.m.raw_io.output(),
      step_test_data=step_test_data,
      infra_step=True)
    return result.stdout.strip()

  def md5(self, name, source, test_data=''):
    return self(name, source, 'md5', test_data)

  def sha1(self, name, source, test_data=''):
    return self(name, source, 'sha1', test_data)

  def sha224(self, name, source, test_data=''):
    return self(name, source, 'sha224', test_data)

  def sha256(self, name, source, test_data=''):
    return self(name, source, 'sha256', test_data)

  def sha384(self, name, source, test_data=''):
    return self(name, source, 'sha384', test_data)

  def sha512(self, name, source, test_data=''):
    return self(name, source, 'sha512', test_data)
