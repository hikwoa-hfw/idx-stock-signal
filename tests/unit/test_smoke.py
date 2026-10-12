import sys
from pathlib import Path


def test_python_version():
    assert sys.version_info >= (3, 12)


def test_project_root_exists():
    root = Path(__file__).resolve().parent.parent.parent
    assert (root / "python").is_dir()
    assert (root / "docs").is_dir()
    assert (root / ".env.example").is_file()
