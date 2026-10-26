import sys
from pathlib import Path

# Add all DataExtraction package locations to sys.path so tests can import modules directly
backend_test_dir = Path(__file__).resolve().parent
repo_root = backend_test_dir.parents[2]
packages_dir = repo_root / "packages"

paths_to_add = [
    str(repo_root),
    str(packages_dir),
    str(packages_dir / "pipeline"),
    str(packages_dir / "infrastructure"),
    str(packages_dir / "scrapers"),
    str(packages_dir / "scrapers" / "federal"),
    str(packages_dir / "scrapers" / "open_map"),
    str(packages_dir / "scrapers" / "openmap_engine"),
    str(packages_dir / "api"),
    str(packages_dir / "api" / "routers"),
    str(repo_root / "scripts" / "db"),
    str(repo_root / "scripts" / "ops"),
]

for p in paths_to_add:
    if p not in sys.path:
        sys.path.insert(0, p)

