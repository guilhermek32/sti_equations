import os
import shutil
import subprocess
from pathlib import Path


def test_deliberate_internal_import_fails_boundary_check(tmp_path) -> None:
    repository = Path(__file__).resolve().parents[2]
    shutil.copytree(repository / "src" / "sti_equations", tmp_path / "src" / "sti_equations")
    config = tmp_path / ".importlinter"
    shutil.copy(repository / ".importlinter", config)
    target = tmp_path / "src" / "sti_equations" / "learning" / "models.py"
    with target.open("a", encoding="utf-8") as source:
        source.write("\nfrom sti_equations.tutoring.engine import EquationEngine\n")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(tmp_path / "src")
    result = subprocess.run(
        ["lint-imports", "--config", str(config), "--no-cache"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert "Packages use public interfaces BROKEN" in result.stdout
