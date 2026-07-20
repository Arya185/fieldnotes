from __future__ import annotations

import ast
import unittest
from pathlib import Path


class OpenAIImportBoundaryTests(unittest.TestCase):
    def test_only_llm_module_imports_openai_sdk(self) -> None:
        backend_dir = Path(__file__).resolve().parents[1] / "backend"
        allowed_path = backend_dir / "agent" / "llm.py"
        violations: list[str] = []

        for path in backend_dir.rglob("*.py"):
            if path == allowed_path:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == "openai" for alias in node.names):
                        violations.append(str(path.relative_to(backend_dir.parent)))
                        break
                if isinstance(node, ast.ImportFrom) and node.module == "openai":
                    violations.append(str(path.relative_to(backend_dir.parent)))
                    break

        self.assertEqual(
            violations,
            [],
            "OpenAI SDK imports must stay isolated to backend/agent/llm.py per rule.md R3.2. "
            f"Violations: {', '.join(sorted(violations))}",
        )


if __name__ == "__main__":
    unittest.main()
