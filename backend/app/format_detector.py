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


def _detect_by_content(content: bytes) -> str:
    if content[:4] == b"PK\x03\x04":
        return "xlsx"
    stripped = content.lstrip()
    if stripped[:1] in (b"{", b"["):
        return "json"
    return "csv"
