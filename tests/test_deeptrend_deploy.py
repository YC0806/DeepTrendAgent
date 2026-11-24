from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class DeployTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.app = self.root / "server's app" / "app"
        self.commands = self.root / "commands"
        self.commands.mkdir()
        self.env = {**os.environ, "PATH": f"{self.commands}{os.pathsep}{os.environ['PATH']}"}
        self.write_command(
            "ssh",
            '#!/bin/bash\nset -eu\n[[ "$#" == 4 && "$1" == -T && "$2" == -- && "$3" == test-server ]]\n'
            'exec /bin/sh -c "$4"\n',
        )
        if not shutil.which("flock"):
            self.write_command(
                "flock",
                "#!/usr/bin/env python3\nimport fcntl, sys\n"
                "fcntl.flock(int(sys.argv[2]), fcntl.LOCK_EX)\n",
            )

    def write_command(self, name: str, contents: str) -> None:
        path = self.commands / name
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o700)

    def deploy(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(REPO_ROOT / "deploy/deploy.sh"), "test-server", str(self.app)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_packages_installs_and_switches_to_a_new_release(self) -> None:
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        first_release = self.app.resolve()
        self.assertTrue(self.app.is_symlink())
        self.assertTrue((first_release / ".opencode/skills/trend-run/SKILL.md").is_file())
        self.assertFalse((first_release / ".opencode/node_modules").exists())
        self.assertFalse((first_release / "example").exists())
        state = self.app.parent / "history.json"
        state.write_text("saved history", encoding="utf-8")

        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.app.resolve(), first_release)
        self.assertIn(f"Previous release: {first_release}", result.stdout)
        self.assertTrue((first_release / "bin/run-deeptrend").is_file())
        self.assertEqual(state.read_text(encoding="utf-8"), "saved history")

    def test_migrates_a_legacy_app_directory_and_retains_its_contents(self) -> None:
        (self.app / "bin").mkdir(parents=True)
        (self.app / ".opencode/skills/trend-run").mkdir(parents=True)
        (self.app / ".opencode/skills/trend-run/SKILL.md").touch()
        (self.app / "bin/run-deeptrend").write_text("legacy runner", encoding="utf-8")

        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.app.is_symlink())
        previous_release = Path(result.stdout.split("Previous release: ", 1)[1].strip())
        self.assertEqual((previous_release / "bin/run-deeptrend").read_text(), "legacy runner")

    def test_checksum_mismatch_keeps_the_active_release(self) -> None:
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        active_release = self.app.resolve()

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "deploy/install-release.sh"), str(self.app), "0" * 64],
            input="corrupted package",
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Package checksum mismatch.", result.stderr)
        self.assertEqual(self.app.resolve(), active_release)
        self.assertFalse(list(active_release.parent.glob(".stage.*")))
