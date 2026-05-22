"""Test file to verify writing works."""
import unittest

class SimpleTest(unittest.TestCase):
    def test_simple(self):
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
