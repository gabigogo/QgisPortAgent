"""Package stream_segmenter as a QGIS-installable zip archive.

Usage
-----
Run from the workspace root or from within the plugin directory::

    python stream_segmenter/scripts/package_plugin.py

The zip is written to ``stream_segmenter/dist/stream_segmenter.zip``.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PLUGIN_NAME = "stream_segmenter"

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
    """Return True when *path* should be included in the distribution zip.

    Args:
        path (Path): Candidate file path (must be under *plugin_root*).
        plugin_root (Path): Absolute path to the plugin root directory.

    Returns:
        bool: True if the file passes all exclusion rules.
    """
    rel_parts = path.relative_to(plugin_root).parts
    if any(part in EXCLUDE_DIRS for part in rel_parts):
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    return True


def package_plugin() -> Path:
    """Build the plugin zip and return its path.

    The archive is structured so that QGIS can install it directly:
    all files are placed under a top-level ``stream_segmenter/`` directory
    inside the zip.

    Returns:
        Path: Absolute path of the created zip file.
    """
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

    print(f"Plugin packaged: {zip_path}")
    return zip_path


if __name__ == "__main__":
    package_plugin()
