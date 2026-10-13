"""Registry store: canonical serialization, lock, atomic replace, optimistic concurrency."""
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import segmently_modules
from segmently_modules.output import UsageError
from segmently_modules.store import RegistryStore, open_store, serialize
from segmently_modules.workspace import Workspace
from tests.helpers import FIXTURE, copy_fixture

ENGINE_ROOT = str(Path(segmently_modules.__file__).resolve().parents[1])


class SerializeTest(unittest.TestCase):
    def test_fixture_round_trips_byte_identical(self):
        text = (FIXTURE / "modules" / "registry.json").read_text(encoding="utf-8")
        self.assertEqual(serialize(json.loads(text)), text)

    def test_unicode_kept_and_key_order_preserved(self):
        self.assertEqual(serialize({"b": "é", "a": [1]}), '{\n  "b": "é",\n  "a": [\n    1\n  ]\n}\n')


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.path = self.root / "modules" / "registry.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_noop_edit_leaves_file_untouched(self):
        before = self.path.read_bytes()
        mtime = self.path.stat().st_mtime_ns
        with RegistryStore(self.path).edit():
            pass
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, mtime)

    def test_edit_saves_changes_and_updates_sha(self):
        with RegistryStore(self.path).edit() as reg:
            reg.raw["modules"]["catalog"]["status"] = "draft"
        self.assertEqual(json.loads(self.path.read_text())["modules"]["catalog"]["status"], "draft")
        self.assertEqual(RegistryStore(self.path).load().sha256, reg.sha256)

    def test_stale_expected_sha_refused_and_file_unchanged(self):
        store = RegistryStore(self.path)
        reg = store.load()
        self.path.write_text(self.path.read_text() + " ", encoding="utf-8")  # someone else wrote
        changed = self.path.read_bytes()
        with self.assertRaises(UsageError) as ctx:
            store.save(reg.raw, reg.sha256)
        self.assertIn("changed since it was read", str(ctx.exception))
        self.assertEqual(self.path.read_bytes(), changed)

    def test_file_mode_kept_and_no_temp_files_left(self):
        os.chmod(self.path, 0o640)
        with RegistryStore(self.path).edit() as reg:
            reg.raw["modules"]["catalog"]["status"] = "draft"
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertEqual([p.name for p in self.path.parent.glob(".registry.json.*")], [])

    def test_updated_at_stamped_only_when_something_changed(self):
        store = RegistryStore(self.path, updated_at_path="metadata.last_updated",
                              clock=lambda: "2030-01-01T00:00:00Z")
        with store.edit():
            pass
        self.assertEqual(json.loads(self.path.read_text())["metadata"]["last_updated"],
                         "2026-01-01T00:00:00Z")
        with store.edit() as reg:
            reg.raw["modules"]["catalog"]["status"] = "draft"
        self.assertEqual(json.loads(self.path.read_text())["metadata"]["last_updated"],
                         "2030-01-01T00:00:00Z")

    def test_open_store_uses_configured_path_and_stamp(self):
        (self.root / ".segmently-modules" / "config.toml").write_text(
            '[registry]\nupdated_at_path = "metadata.last_updated"\n', encoding="utf-8")
        store = open_store(Workspace.load(self.root))
        self.assertEqual(store.path, self.path.resolve())
        self.assertEqual(store.updated_at_path, "metadata.last_updated")


class LockTest(unittest.TestCase):
    def test_second_writer_waits_or_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text('{"modules": {}}\n', encoding="utf-8")
            holder = subprocess.Popen(
                [sys.executable, "-c",
                 "import sys, time\n"
                 f"sys.path.insert(0, {ENGINE_ROOT!r})\n"
                 "from pathlib import Path\n"
                 "from segmently_modules.store import RegistryStore\n"
                 f"with RegistryStore(Path({str(path)!r})).locked():\n"
                 "    print('locked', flush=True)\n"
                 "    time.sleep(1.5)\n"
                 "    print('releasing', flush=True)\n"],
                stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                with self.assertRaises(UsageError) as ctx:
                    with RegistryStore(path, lock_timeout_s=0.2).locked():
                        pass
                self.assertIn("locked by another writer", str(ctx.exception))
                with RegistryStore(path, lock_timeout_s=10).locked():
                    # acquired only after the holder printed "releasing" and let go
                    self.assertEqual(holder.stdout.readline().strip(), "releasing")
            finally:
                holder.wait(timeout=10)
                holder.stdout.close()

    def test_non_contention_errno_raises_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text('{"modules": {}}\n', encoding="utf-8")
            store = RegistryStore(path, lock_timeout_s=10)
            start = time.monotonic()
            with mock.patch("segmently_modules.store._try_lock",
                             side_effect=OSError(errno.ENOLCK, "No locks available")):
                with self.assertRaises(UsageError) as ctx:
                    with store.locked():
                        pass
            elapsed = time.monotonic() - start
            self.assertIn("cannot lock", str(ctx.exception))
            self.assertLess(elapsed, 2.0)


class AtomicWriteFailureTest(unittest.TestCase):  # AC-006
    def test_failed_rename_keeps_original_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = copy_fixture(tmp) / "modules" / "registry.json"
            before = path.read_bytes()
            with mock.patch("segmently_modules.store.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    with RegistryStore(path).edit() as reg:
                        reg.raw["modules"]["catalog"]["status"] = "draft"
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual([p.name for p in path.parent.glob(".registry.json.*")], [])


if __name__ == "__main__":
    unittest.main()
