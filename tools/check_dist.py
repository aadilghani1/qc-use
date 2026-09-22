"""Check that the wheel contains runtime assets and required attribution."""

from pathlib import Path
from zipfile import ZipFile

wheels = list(Path("dist").glob("*.whl"))
assert wheels, "No wheel found; run uv build first."
for wheel in wheels:
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        for suffix in (
            "/licenses/LICENSE",
            "/licenses/NOTICE",
            "/engine/snapshot.js",
            "/watch.html",
            "/SKILL.md",
            "/demo/tests/avatar.png",
        ):
            assert any(name.endswith(suffix) for name in names), f"Missing {suffix} in {wheel}"
        notice = next(name for name in names if name.endswith("/licenses/NOTICE"))
        assert b"Browser Use" in archive.read(notice)
        assert not any("node_modules" in name or "tools/preview" in name for name in names)
    print(f"Checked assets and attribution in {wheel}")
