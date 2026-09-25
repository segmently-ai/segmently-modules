import tempfile
import unittest
from unittest import mock

from modsys import __version__
from tests.helpers import copy_fixture, run


class CliTest(unittest.TestCase):
    def test_version(self):
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)

    def test_missing_verb_is_usage_error(self):
        code, _, err = run()
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())

    def test_keyboard_interrupt_is_exit_130_without_a_traceback(self):
        # Ctrl-C during a lock wait or at a `create` prompt: exit 130, one stderr line
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("modsys.query.run_list", side_effect=KeyboardInterrupt):
            try:
                code, out, err = run("list", "--root", str(copy_fixture(tmp)))
            except KeyboardInterrupt:  # unittest would abort the whole run on a bare re-raise
                self.fail("KeyboardInterrupt escaped modsys.cli.main")
        self.assertEqual((code, out, err), (130, "", "modsys: interrupted\n"))
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
