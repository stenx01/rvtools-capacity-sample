from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import shutil

import pandas as pd

from rvcap.config import SHEETS
from rvcap.paths import data_raw, ensure_dirs
from rvcap.util import (
    coerce_numerics,
    excel_serial_to_datetime,
    parse_filename,
    sha256_file,
    uniquify_headers,
)
from rvcap.warehouse import (
    delete_entity_snapshot,
    load_catalog,
    save_catalog,
    write_entity,
)


def discover_raw_files(extra: Path | None = None) -> list[Path]:
    ensure_dirs()
    files = sorted(data_raw().glob("*.xlsx"))
    if extra is not None:
        extra = extra.resolve()
        if extra not in files:
            files.append(extra)
    # Also pick up extracts left in the project root.
    root_files = sorted(data_raw().parent.parent.glob("RVTools_*.xlsx"))
    for path in root_files:
        if path not in files:
            files.append(path)
    return files


def _read_sheet(excel: pd.ExcelFile, name: str) -> pd.DataFrame:
    if name not in excel.sheet_names:
        return pd.DataFrame()
    df = excel.parse(name, header=0)
    if df.empty:
        return df
    df.columns = uniquify_headers([str(c) for c in df.columns])
    df = coerce_numerics(df)
    return df


def _meta_values(meta: pd.DataFrame, source: pd.DataFrame, parsed: dict, path: Path) -> dict:
    server = None
    version = None
    created = None
    if not meta.empty:
        row = meta.iloc[0]
        version = row.get("RVTools version") or row.get("RVTools major version")
        server = row.get("Server")
        created = excel_serial_to_datetime(row.get("xlsx creation datetime"))
    vcenter = parsed.get("vcenter")
    if not vcenter and not source.empty:
        vcenter = str(source.iloc[0].get("Name") or "unknown")
    if not vcenter and server:
        vcenter = str(server).split(".")[0]
    if not vcenter:
        vcenter = path.stem
    snapshot_date = parsed.get("snapshot_date")
    if snapshot_date is None and created is not None:
        snapshot_date = created.date()
    if snapshot_date is None:
        snapshot_date = date.today()
    environment = parsed.get("environment") or "unknown"
    return {
        "vcenter": str(vcenter),
        "environment": str(environment),
        "server": None if server is None or (isinstance(server, float) and pd.isna(server)) else str(server),
        "rvtools_version": None if version is None or (isinstance(version, float) and pd.isna(version)) else str(version),
        "snapshot_date": snapshot_date,
        "created_at": created,
    }


def _stamp(df: pd.DataFrame, meta: dict, source_file: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["_snapshot_date"] = meta["snapshot_date"]
    out["_vcenter"] = meta["vcenter"]
    out["_environment"] = meta["environment"]
    out["_source_file"] = source_file
    return out


def ingest_file(path: Path, replace: bool = True) -> dict:
    path = path.resolve()
    digest = sha256_file(path)
    catalog = load_catalog()
    if not catalog.empty and digest in set(catalog["sha256"]):
        row = catalog.loc[catalog["sha256"] == digest].iloc[0]
        return {
            "status": "skipped",
            "reason": "already ingested",
            "source_file": path.name,
            "snapshot_date": row["snapshot_date"],
            "vcenter": row["vcenter"],
        }

    excel = pd.ExcelFile(path, engine="openpyxl")
    parsed = parse_filename(path)
    sheets = {name: _read_sheet(excel, name) for name in SHEETS}
    meta = _meta_values(sheets["vMetaData"], sheets["vSource"], parsed, path)

    if not catalog.empty:
        clash = catalog[
            (catalog["snapshot_date"] == meta["snapshot_date"])
            & (catalog["vcenter"] == meta["vcenter"])
        ]
        if not clash.empty:
            if not replace:
                return {
                    "status": "skipped",
                    "reason": "snapshot already exists",
                    "source_file": path.name,
                    **{k: meta[k] for k in ("snapshot_date", "vcenter")},
                }
            for entity in SHEETS:
                delete_entity_snapshot(entity, meta["snapshot_date"], meta["vcenter"])
            catalog = catalog.drop(clash.index)

    for entity, frame in sheets.items():
        stamped = _stamp(frame, meta, path.name)
        write_entity(entity, meta["snapshot_date"], meta["vcenter"], stamped)

    n_vms = 0 if sheets["vInfo"].empty else len(sheets["vInfo"])
    row = {
        "sha256": digest,
        "source_file": path.name,
        "snapshot_date": meta["snapshot_date"],
        "vcenter": meta["vcenter"],
        "environment": meta["environment"],
        "server": meta["server"],
        "rvtools_version": meta["rvtools_version"],
        "n_vms": n_vms,
        "ingested_at": datetime.now().isoformat(timespec="seconds"),
    }
    catalog = pd.concat([catalog, pd.DataFrame([row])], ignore_index=True)
    save_catalog(catalog)
    dest = data_raw() / path.name
    if path.resolve() != dest.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return {"status": "ingested", **row}


def ingest_all(extra: Path | None = None) -> list[dict]:
    results = []
    for path in discover_raw_files(extra):
        results.append(ingest_file(path))
    return results
