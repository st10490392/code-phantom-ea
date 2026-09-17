from pathlib import Path


def test_python_generated_artifacts_are_ignored():
    patterns = set(Path(".gitignore").read_text(encoding="utf-8").splitlines())
    assert {"__pycache__/", "*.py[cod]", ".pytest_cache/", ".venv/"} <= patterns
