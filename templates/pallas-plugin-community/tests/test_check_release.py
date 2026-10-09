import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_release.py"


class ReleaseCheckTests(unittest.TestCase):
    def run_copied_checker(self, mutate_init):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("__init__.py", "CHANGELOG.md", "community-index.entry.json"):
                shutil.copy(ROOT / name, root / name)
            init_path = root / "__init__.py"
            init_path.write_text(mutate_init(init_path.read_text(encoding="utf-8")), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECKER), "--root", str(root), "--tag", "v0.1.0"],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_matching_release_passes(self):
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--tag", "v0.1.0"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tag_drift_fails(self):
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--tag", "v0.1.1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_entry_version_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("__init__.py", "CHANGELOG.md", "community-index.entry.json"):
                shutil.copy(ROOT / name, root / name)
            entry_path = root / "community-index.entry.json"
            entry = json.loads(entry_path.read_text(encoding="utf-8"))
            entry["version"] = "0.1.1"
            entry_path.write_text(json.dumps(entry), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CHECKER), "--root", str(root), "--tag", "v0.1.0"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)

    def test_changelog_version_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("__init__.py", "CHANGELOG.md", "community-index.entry.json"):
                shutil.copy(ROOT / name, root / name)
            changelog = root / "CHANGELOG.md"
            changelog.write_text(changelog.read_text().replace("[0.1.0]", "[0.1.1]"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CHECKER), "--root", str(root), "--tag", "v0.1.0"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)

    def test_metadata_version_drift_fails(self):
        result = self.run_copied_checker(lambda source: source.replace('"version": "0.1.0"', '"version": "0.1.1"'))
        self.assertNotEqual(result.returncode, 0)

    def test_unbound_metadata_call_is_rejected(self):
        def add_decoy(source):
            source = source.replace(
                "__plugin_meta__ = PluginMetadata(",
                "__plugin_meta__ = None\n\nunused = PluginMetadata(",
            )
            return source

        result = self.run_copied_checker(add_decoy)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
