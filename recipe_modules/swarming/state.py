# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from enum import Enum

class TaskState(Enum):
  """Enum representing Swarming task states.
  States must be kept in sync with
  https://cs.chromium.org/chromium/infra/luci/appengine/swarming/swarming_rpcs.py?q=TaskState\(
  """
  # The task completed with an exit code of 0.
  SUCCESS = 0
  # The task completed with a nonzero exit code
  TASK_FAILURE = 1
  # The task is in an unknown state; the server cannot be communicated with due
  # to an RPC-level failure.
  RPC_FAILURE = 2
  # The task ran for longer than the allowed time.
  TIMED_OUT = 3
  # The task never ran due to a lack of capacity: all other machines of matching
  # dimensions were unavailable.
  EXPIRED = 4
  # The task never ran due to its requested swarming dimensions not matching
  # any machine available.
  NO_RESOURCE = 5
  # The task ran but the bot had an internal failure, unrelated to the task
  # itself.
  BOT_DIED = 6
  # The task never ran and was manually killed via the 'cancel' API
  CANCELED = 7
  # The task ran but was manually killed via the 'cancel' API
  KILLED = 8
