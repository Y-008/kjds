"""Create a deterministic ZIP containing all current market-recon sources."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "output" / "market_recon"
DEFAULT_OUTPUT = SOURCE_ROOT / "market_recon_bundle.zip"
FIXED_ZIP_TIME = (2026, 8, 2, 0, 0, 0)


def source_files(
    logistics_observations_path: Path | None = None,
) -> list[tuple[Path, str]]:
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
    optional: list[tuple[Path, str]] = []
    if logistics_observations_path is not None:
        if not logistics_observations_path.is_file():
            raise FileNotFoundError(
                f"Missing structured logistics observations: {logistics_observations_path}"
            )
        optional.append(
            (logistics_observations_path, "logistics_evidence_hits.json")
        )
    return required + browser + optional


def package_bundle(
    output_path: Path = DEFAULT_OUTPUT,
    *,
    logistics_observations_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, archive_name in source_files(logistics_observations_path):
            info = zipfile.ZipInfo(archive_name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--logistics-observations",
        type=Path,
        help="Optional structured RU-002 observation JSON; raw user files are never added implicitly.",
    )
    args = parser.parse_args()
    sources = source_files(args.logistics_observations)
    output = package_bundle(
        args.output,
        logistics_observations_path=args.logistics_observations,
    )
    print(f"Created {output} ({output.stat().st_size} bytes) from {len(sources)} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
