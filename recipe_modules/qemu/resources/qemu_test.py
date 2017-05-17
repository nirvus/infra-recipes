"""Unit tests for the QEMU wrapper script."""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import qemu


class LineEmitterTest(unittest.TestCase):

  def setUp(self):
    self.lines = []
    self.instance = qemu.LineEmitter(self.lines.append)

  def expect(self, lines):
    self.assertEqual(lines, self.lines)

  def test_single_line_with_trailing_newlines(self):
    self.instance.read('12\n\n\n')
    self.expect(['12\n', '\n', '\n'])

  def test_split_line_with_remainder(self):
    self.instance.read('12')
    self.instance.read('34\n5')
    self.expect(['1234\n'])

  def test_one_chunk_per_link(self):
    self.instance.read('12\n')
    self.instance.read('34\n')
    self.instance.read('56\n')
    self.expect(['12\n', '34\n', '56\n'])

  def test_multiple_lines_in_one_chunk(self):
    self.instance.read('1')
    self.instance.read('23\n45\n6')
    self.instance.read('\n7')
    self.expect(['123\n', '45\n', '6\n'])


if __name__ == '__main__':
    unittest.main()
