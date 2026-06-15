import ast
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_is_the_only_dependency_source() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["dependencies"]
    assert not (ROOT / "requirements.txt").exists()


def test_active_contributor_guidance_does_not_reference_requirements_file() -> None:
    guidance = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "CLAUDE.md",
        ROOT / ".agents" / "skills" / "supportfaq-git-flow" / "SKILL.md",
        ROOT / ".agents" / "skills" / "supportfaq-next-step-planner" / "SKILL.md",
        ROOT / ".agents" / "skills" / "supportfaq-project-navigator" / "SKILL.md",
    ]

    for path in guidance:
        assert "requirements.txt" not in path.read_text(encoding="utf-8"), path


def test_application_packages_have_meaningful_docstrings() -> None:
    initializers = (ROOT / "app").rglob("__init__.py")

    for path in initializers:
        docstring = ast.get_docstring(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        assert docstring, path
        assert "placeholder" not in docstring.lower(), path
