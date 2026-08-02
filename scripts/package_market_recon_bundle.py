"""Create a deterministic ZIP containing all current market-recon sources."""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "output" / "market_recon"
DEFAULT_OUTPUT = SOURCE_ROOT / "market_recon_bundle.zip"
FIXED_ZIP_TIME = (2026, 8, 2, 0, 0, 0)


def source_files() -> list[tuple[Path, str]]:
    required = [
        (SOURCE_ROOT / "full_catalog.json", "full_catalog.json"),
        (SOURCE_ROOT / "full_product_info.json", "full_product_info.json"),
        (SOURCE_ROOT / "analytics_by_window.json", "analytics_by_window.json"),
        (SOURCE_ROOT / "finance_by_month.json", "finance_by_month.json"),
        (SOURCE_ROOT / "supply_1688" / "supply_crawl.json", "supply_1688/supply_crawl.json"),
    ]
    browser = [
        (path, f"browser_capture/{path.name}")
        for path in sorted((ROOT / "output" / "browser_capture").glob("*.json"))
    ]
    missing = [str(path) for path, _ in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing required market-recon sources: {', '.join(missing)}")
    return required + browser


def package_bundle(output_path: Path = DEFAULT_OUTPUT) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, archive_name in source_files():
            info = zipfile.ZipInfo(archive_name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output_path


def main() -> int:
    output = package_bundle()
    print(f"Created {output} ({output.stat().st_size} bytes) from {len(source_files())} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
