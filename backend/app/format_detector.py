import io
import json
from pathlib import Path

import pandas as pd

SUPPORTED_FORMATS = {"csv", "json", "xlsx"}


def detect_format(filename: str, content: bytes) -> str:
    """Detect the source format from the extension, falling back to content sniffing
    when the extension is missing, wrong, or the file doesn't actually parse as claimed."""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in SUPPORTED_FORMATS and _content_matches(suffix, content):
        return suffix
    return _detect_by_content(content)


def _content_matches(fmt: str, content: bytes) -> bool:
    try:
        if fmt == "json":
            json.loads(content)
        elif fmt == "csv":
            pd.read_csv(io.BytesIO(content), nrows=5)
        elif fmt == "xlsx":
            pd.read_excel(io.BytesIO(content), nrows=5)
        return True
    except Exception:
        return False


# Magic-byte signatures for common formats we deliberately do NOT support for ETL
# (no tabular structure to load into a DataFrame). Detected purely so the upload
# honestly reports what the file actually is ("detected as jpg") instead of
# silently mislabeling it "csv" and failing later with a confusing binary-parse
# error - see _load_dataframe's rejection message for where that surfaces.
_KNOWN_UNSUPPORTED_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF", "pdf"),
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
]


def _detect_by_content(content: bytes) -> str:
    if content[:4] == b"PK\x03\x04":
        return "xlsx"
    stripped = content.lstrip()
    if stripped[:1] in (b"{", b"["):
        return "json"
    for signature, fmt in _KNOWN_UNSUPPORTED_SIGNATURES:
        if content.startswith(signature):
            return fmt
    return "csv"
