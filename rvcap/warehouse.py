from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from rvcap.paths import warehouse_dir


def catalog_path() -> Path:
    return warehouse_dir() / "_catalog.parquet"


def entity_dir(entity: str) -> Path:
    return warehouse_dir() / entity.lower()


def snapshot_filename(snapshot_date: date, vcenter: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in vcenter)
    return f"{snapshot_date.isoformat()}__{safe}.parquet"


def load_catalog() -> pd.DataFrame:
    path = catalog_path()
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "sha256",
                "source_file",
                "snapshot_date",
                "vcenter",
                "environment",
                "server",
                "rvtools_version",
                "n_vms",
                "ingested_at",
            ]
        )
    df = pd.read_parquet(path)
    if not df.empty:
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    return df


def save_catalog(df: pd.DataFrame) -> None:
    warehouse_dir().mkdir(parents=True, exist_ok=True)
    df.to_parquet(catalog_path(), index=False)


def write_entity(entity: str, snapshot_date: date, vcenter: str, df: pd.DataFrame) -> Path:
    folder = entity_dir(entity)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / snapshot_filename(snapshot_date, vcenter)
    df.to_parquet(path, index=False)
    return path


def delete_entity_snapshot(entity: str, snapshot_date: date, vcenter: str) -> None:
    path = entity_dir(entity) / snapshot_filename(snapshot_date, vcenter)
    if path.exists():
        path.unlink()


def load_entity(entity: str, through: date | None = None) -> pd.DataFrame:
    folder = entity_dir(entity)
    if not folder.exists():
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for path in sorted(folder.glob("*.parquet")):
        frame = pd.read_parquet(path)
        if "_snapshot_date" in frame.columns:
            frame["_snapshot_date"] = pd.to_datetime(frame["_snapshot_date"]).dt.date
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if through is not None and "_snapshot_date" in df.columns:
        df = df[df["_snapshot_date"] <= through]
    return df


def available_snapshot_dates() -> list[date]:
    catalog = load_catalog()
    if catalog.empty:
        return []
    return sorted(set(catalog["snapshot_date"]))


def snapshot_as_of(month: str | None = None, as_of: date | None = None) -> date | None:
    dates = available_snapshot_dates()
    if not dates:
        return None
    if as_of is not None:
        prior = [d for d in dates if d <= as_of]
        return prior[-1] if prior else None
    if month:
        year, mon = (int(part) for part in month.split("-"))
        in_month = [d for d in dates if d.year == year and d.month == mon]
        return in_month[-1] if in_month else None
    return dates[-1]


def facts_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".facts.json")


def write_facts(pdf_path: Path, payload: dict) -> Path:
    path = facts_path_for(pdf_path)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
