"""Critical-path QA in plain words. Powered by TypeSafe Jev."""

__version__ = "0.1.0"


def build_identity():
    """Identify installed source even when multiple revisions share a package version."""
    import hashlib
    from pathlib import Path

    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.suffix in {".py", ".js", ".html"}:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()
