from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from rvcap.ingest import ingest_all
from rvcap.metrics import build_pack, kpis
from rvcap.paths import ensure_dirs
from rvcap.report import render_pdf
from rvcap.warehouse import available_snapshot_dates, load_catalog, snapshot_as_of


def _print_results(results: list[dict]) -> int:
    if not results:
        print("No RVTools .xlsx files found in data\\raw or the project folder.")
        return 1
    for row in results:
        status = row.get("status")
        print(
            f"{status:10} {row.get('source_file', '')}  "
            f"{row.get('snapshot_date')}  {row.get('vcenter')}  "
            f"{row.get('reason', '')}"
        )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    extra = Path(args.file).resolve() if args.file else None
    return _print_results(ingest_all(extra))


def cmd_status(_args: argparse.Namespace) -> int:
    catalog = load_catalog()
    if catalog.empty:
        print("Warehouse is empty. Run: python -m rvcap ingest")
        return 0
    print(catalog.to_string(index=False))
    print(f"\nSnapshots: {len(available_snapshot_dates())}")
    return 0


def _resolve_as_of(args: argparse.Namespace) -> date:
    if args.date:
        return date.fromisoformat(args.date)
    as_of = snapshot_as_of(month=args.month)
    if as_of is None:
        raise SystemExit("No snapshots in the warehouse. Run ingest first.")
    return as_of


def cmd_report(args: argparse.Namespace) -> int:
    as_of = _resolve_as_of(args)
    pack = build_pack(as_of)
    kind = args.period
    pdf = render_pdf(pack, kind, month=args.month)
    facts = pdf.with_suffix(".facts.json")
    k = kpis(pack)
    print(f"Wrote {pdf}")
    print(f"Wrote {facts}")
    print(
        f"{k['powered_on_vms']} powered-on VMs  |  "
        f"mem {k['memory_used_pct']}%  |  cpu {k['cpu_weighted_pct']}%  |  "
        f"ds free {k['datastore_free_pct']}%  |  history {k['history_points']}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rvcap",
        description="Ingest weekly RVTools extracts into parquet and render capacity PDFs.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Load RVTools xlsx files into the parquet warehouse")
    ingest.add_argument("file", nargs="?", help="Optional extra xlsx path")
    ingest.set_defaults(func=cmd_ingest)

    status = sub.add_parser("status", help="Show ingested snapshots")
    status.set_defaults(func=cmd_status)

    report = sub.add_parser("report", help="Render a capacity PDF from the warehouse")
    report.add_argument("--period", choices=("monthly", "weekly"), default="monthly")
    report.add_argument("--month", help="YYYY-MM (uses last snapshot in that month)")
    report.add_argument("--date", help="YYYY-MM-DD snapshot date")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
