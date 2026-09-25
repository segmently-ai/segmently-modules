import unittest

from modsys import __version__
from tests.helpers import run


class CliTest(unittest.TestCase):
    def test_version(self):
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)

    def test_missing_verb_is_usage_error(self):
        code, _, err = run()
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())


if __name__ == "__main__":
    unittest.main()
