import unittest
from toy_api import normalize_tag

class TagTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_tag("  Ab C  "), "ab c")
