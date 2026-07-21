from pathlib import Path

from apps.control_plane.write_paths import validate_repository_write_paths

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    validate_repository_write_paths(ROOT)
    print("Write-path registry and source boundaries are valid.")
