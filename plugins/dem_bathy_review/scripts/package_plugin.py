"""Package dem_bathy_review as a QGIS-installable zip archive."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PLUGIN_NAME = "dem_bathy_review"
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    "tests",
    "docs",
    "scripts",
    "dist",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def should_include(path: Path, plugin_root: Path) -> bool:
    """Return True when the path should be included in the plugin zip."""
    rel_parts = path.relative_to(plugin_root).parts
    if any(part in EXCLUDE_DIRS for part in rel_parts):
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    return True


def package_plugin() -> Path:
    """Build the plugin zip file and return its path."""
    script_dir = Path(__file__).resolve().parent
    plugin_root = script_dir.parent
    output_dir = plugin_root / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)

    zip_path = output_dir / f"{PLUGIN_NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for path in plugin_root.rglob("*"):
            if path.is_dir() or not should_include(path, plugin_root):
                continue
            archive_name = Path(PLUGIN_NAME) / path.relative_to(plugin_root)
            zip_file.write(path, archive_name.as_posix())

    return zip_path


def main() -> None:
    """CLI entrypoint."""
    zip_path = package_plugin()
    print(f"Created: {zip_path}")


if __name__ == "__main__":
    main()
