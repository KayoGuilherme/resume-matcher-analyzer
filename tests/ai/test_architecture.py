"""Only the provider packages may talk to a provider: everything else uses the protocols."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "app"
PROVIDER_MODULES = {"anthropic", "openai", "sentence_transformers", "httpx", "httpx2"}
ALLOWED = (SRC / "ai" / "llm", SRC / "ai" / "embeddings")


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_the_llm_and_embeddings_packages_import_provider_libraries() -> None:
    offenders = [
        f"{path.relative_to(SRC)} imports {sorted(roots & PROVIDER_MODULES)}"
        for path in sorted(SRC.rglob("*.py"))
        if not any(path.is_relative_to(allowed) for allowed in ALLOWED)
        if (roots := _imported_roots(path)) & PROVIDER_MODULES
    ]

    assert offenders == []


def test_the_scan_sees_the_provider_packages() -> None:
    adapters = {
        path.name for path in (SRC / "ai").rglob("*.py") if _imported_roots(path) & PROVIDER_MODULES
    }

    assert {"openai_client.py", "anthropic_client.py", "local.py"} <= adapters


def test_the_single_file_modules_of_the_old_layout_are_gone() -> None:
    assert not (SRC / "ai" / "llm.py").exists()
    assert not (SRC / "ai" / "embeddings.py").exists()


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_the_matching_package_is_scanned_and_imports_no_provider_library() -> None:
    files = sorted((SRC / "ai" / "matching").glob("*.py"))

    assert {"engine.py", "judge.py", "deterministic.py", "retrieval.py"} <= {f.name for f in files}
    assert all(not (_imported_roots(f) & PROVIDER_MODULES) for f in files)


def test_the_matching_package_depends_on_no_feature_package() -> None:
    features = ("app.resumes", "app.jobs", "app.profile", "app.analyses", "app.health")
    offenders = [
        f"{path.name} imports {module}"
        for path in sorted((SRC / "ai" / "matching").glob("*.py"))
        for module in _imported_modules(path)
        if module.startswith(features)
    ]

    assert offenders == []


def test_the_matching_package_does_not_import_the_database_layer() -> None:
    offenders = [
        path.name
        for path in sorted((SRC / "ai" / "matching").glob("*.py"))
        if any(m.startswith(("sqlalchemy", "app.core.db")) for m in _imported_modules(path))
    ]

    assert offenders == []
