from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.sandbox.runner import run_generated_analysis


class SandboxSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.artifacts = self.workspace / "artifacts"
        self.artifacts.mkdir()
        (self.workspace / "safe.txt").write_text("safe", encoding="utf-8")
        (self.workspace / "data.csv").write_text("value\n1\n2\n3\n", encoding="utf-8")
        self.outside = Path(self.temp_dir.name) / "outside.txt"
        self.outside.write_text("outside", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_workspace_read_and_artifact_write_still_work(self) -> None:
        result = self._run(
            "text = read_text('safe.txt')\n"
            "entries = list_workspace()\n"
            "write_artifact('reports/summary.txt', text)\n"
            "write_result({'summary': 'ok', 'metrics': {'entry_count': int(len(entries)), 'text': text}})\n"
        )
        self.assertEqual(result.result_payload["summary"], "ok")
        self.assertGreaterEqual(result.result_payload["metrics"]["entry_count"], 2)
        self.assertEqual((self.artifacts / "reports" / "summary.txt").read_text(encoding="utf-8"), "safe")

    def test_parent_traversal_fails(self) -> None:
        self._assert_violation("read_text('../outside.txt')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_absolute_path_fails(self) -> None:
        self._assert_violation("read_text('/etc/passwd')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_symlink_escape_fails(self) -> None:
        link_path = self.workspace / "escape.txt"
        try:
            link_path.symlink_to(self.outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self._assert_violation("read_text('escape.txt')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_pathlib_import_fails(self) -> None:
        self._assert_violation("from pathlib import Path\nwrite_result({'summary': str(Path.home()), 'metrics': {}})\n")

    def test_os_import_fails(self) -> None:
        self._assert_violation("import os\nwrite_result({'summary': str(os.listdir('/')), 'metrics': {}})\n")

    def test_open_builtin_fails(self) -> None:
        self._assert_violation("open('/etc/passwd').read()\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_windows_drive_path_fails(self) -> None:
        self._assert_violation("read_text('C:\\\\Windows\\\\System32\\\\drivers\\\\etc\\\\hosts')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_unc_path_fails(self) -> None:
        self._assert_violation("read_text('\\\\\\\\server\\\\share\\\\file.txt')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_write_outside_artifacts_fails(self) -> None:
        self._assert_violation("write_artifact('../escape.txt', 'bad')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_pandas_read_absolute_path_fails(self) -> None:
        self._assert_violation("import pandas as pd\npd.read_csv('/etc/passwd')\nwrite_result({'summary': 'bad', 'metrics': {}})\n")

    def test_pandas_write_outside_artifacts_fails(self) -> None:
        self._assert_violation(
            "import pandas as pd\n"
            "frame = pd.DataFrame({'x': [1]})\n"
            "frame.to_csv('../escape.csv', index=False)\n"
            "write_result({'summary': 'bad', 'metrics': {}})\n"
        )

    def test_matplotlib_write_outside_artifacts_fails(self) -> None:
        self._assert_violation(
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1, 2], [3, 4])\n"
            "save_chart('../escape.png')\n"
            "write_result({'summary': 'bad', 'metrics': {}})\n"
        )

    @unittest.skipUnless(os.name == "nt", "Windows-only containment test")
    def test_windows_infinite_loop_terminates(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            run_generated_analysis(
                workspace_root=self.workspace,
                artifacts_dir=self.artifacts,
                answer_id="win_loop",
                script_source="while True:\n    pass\n",
                timeout_seconds=1,
            )
        self.assertFalse((self.artifacts / "win_loop_result.json").exists())

    @unittest.skipUnless(os.name == "nt", "Windows-only containment test")
    def test_windows_memory_exhaustion_is_blocked(self) -> None:
        with self.assertRaises(RuntimeError):
            run_generated_analysis(
                workspace_root=self.workspace,
                artifacts_dir=self.artifacts,
                answer_id="win_memory",
                script_source="chunks=[]\nwhile True:\n    chunks.append('x' * (1024 * 1024))\n",
                timeout_seconds=5,
            )
        self.assertFalse((self.artifacts / "win_memory_result.json").exists())

    def _run(self, script_source: str):
        return run_generated_analysis(
            workspace_root=self.workspace,
            artifacts_dir=self.artifacts,
            answer_id="security_case",
            script_source=script_source,
        )

    def _assert_violation(self, script_source: str) -> None:
        with self.assertRaises(RuntimeError):
            self._run(script_source)


if __name__ == "__main__":
    unittest.main()
