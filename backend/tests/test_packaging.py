from pathlib import Path
import tomllib


def test_mysql_auth_crypto_dependency_is_declared() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("cryptography") for dependency in dependencies)
