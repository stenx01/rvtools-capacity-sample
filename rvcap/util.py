from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

FILENAME_RE = re.compile(
    r"RVTools_(?P<env>.+)_vCenter_(?P<vcenter>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def uniquify_headers(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for raw in columns:
        name = str(raw).strip()
        if name in seen:
            seen[name] += 1
            suffix = "" if seen[name] == 1 else str(seen[name])
            out.append(f"{name}__custom{suffix}")
        else:
            seen[name] = 0
            out.append(name)
    return out


def excel_serial_to_datetime(value) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        serial = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        return None
    if serial < 20000 or serial > 80000:
        return None
    return datetime(1899, 12, 30) + timedelta(days=serial)


def coerce_numerics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if str(column).startswith("_"):
            continue
        if pd.api.types.is_numeric_dtype(out[column]):
            continue
        converted = pd.to_numeric(out[column], errors="coerce")
        if converted.notna().mean() >= 0.5:
            out[column] = converted
    return out


def parse_filename(path: Path) -> dict:
    match = FILENAME_RE.search(path.stem)
    if not match:
        return {"environment": None, "vcenter": None, "snapshot_date": None}
    return {
        "environment": match.group("env"),
        "vcenter": match.group("vcenter"),
        "snapshot_date": datetime.strptime(match.group("date"), "%Y-%m-%d").date(),
    }


def boolish(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    text = series.astype(str).str.strip().str.lower()
    return text.isin(("true", "1", "yes", "poweredon"))
