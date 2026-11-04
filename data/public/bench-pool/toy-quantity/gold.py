import unittest
from toy_api import parse_quantity

class ParseQuantityTests(unittest.TestCase):
    def test_reject_non_digits(self):
        with self.assertRaises(ValueError) as caught:
            parse_quantity("abc")
        self.assertIn("digits", str(caught.exception))
