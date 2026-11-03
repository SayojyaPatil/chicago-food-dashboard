"""The API must start both from the repo root and from inside backend/ (Railway)."""

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EntrypointTests(unittest.TestCase):
    def test_imports_from_inside_backend_folder(self):
        result = subprocess.run([sys.executable, "-c", "import main; print(main.app.title)"],
                                cwd=ROOT / "backend", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_imports_from_repo_root(self):
        result = subprocess.run([sys.executable, "-c", "import backend.main"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()