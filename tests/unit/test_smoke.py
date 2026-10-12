import sys
from pathlib import Path


def test_python_version():
    assert sys.version_info >= (3, 12)


def test_project_root_exists():
    root = Path(__file__).resolve().parent.parent.parent
    assert (root / "python").is_dir()
    assert (root / "docs").is_dir()
    assert (root / "docs" / "03_plan_ai_stock_signal_BEI_daily.md").is_file()
    assert (root / "docs" / "04_ai_agent_coding_development_guide_BEI_stock_signal.md").is_file()
    assert (root / ".env.example").is_file()
    assert (root / "PROJECT_RULES.md").is_file()
    assert (root / "summary.md").is_file()
    assert (root / "walkthrough.md").is_file()
