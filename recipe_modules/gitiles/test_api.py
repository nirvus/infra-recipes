# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import hashlib

from recipe_engine import recipe_test_api


class GitilesTestApi(recipe_test_api.RecipeTestApi):

  def hash(self, *bases):
    return hashlib.sha1(':'.join(bases)).hexdigest()

  def refs(self, step_name, *refs):
    return self.step_data(
        step_name,
        self.m.json.output({
          ref[0]: ref[1] for ref in refs
        })
    )

  def log(self, step_name, s, n=3):
    commits = []
    for i in xrange(n):
      commit = 'fake %s hash %d' % (s, i)
      name = 'Fake %s' % (s)
      email = 'fake_%s@fake_%i.email.com' % (s, i)
      commits.append({
          'id': self.hash(commit),
          'tree': self.hash('tree', commit),
          'parents': [self.hash('parent', commit)],
          'author': {
              'name': name,
              'email': email,
              'time': 'Mon Jan 01 00:00:00 2015',
          },
          'committer': {
              'name': name,
              'email': email,
              'time': 'Mon Jan 01 00:00:00 2015',
          },
          'message': 'fake %s msg %d' % (s, i),
          'tree_diff': [{
              'type': 'add',
              'old_id': 40 * '0',
              'old_mode': 0,
              'new_id': self.hash('file', f, commit),
              'new_mode': 33188,
              'new_path': f,
          } for f in ['%s.py' % (chr(i + ord('a')))]],
      })
    return self.step_data(step_name, self.m.json.output(commits))

  def fetch(self, step_name, data):
    return self.m.url.text(step_name, base64.b64encode(data))
