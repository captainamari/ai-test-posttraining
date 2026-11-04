import unittest
from toy_api import is_positive_integer

class IntegerTests(unittest.TestCase):
    def test_values(self):
        self.assertTrue(is_positive_integer(1))
        for value in (0, -1, True):
            with self.subTest(value=value):
                self.assertFalse(is_positive_integer(value))
