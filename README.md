# RVTools capacity reporting

Weekly RVTools Excel dumps go into `data/raw`. The tool stores every snapshot as parquet and renders weekly and monthly PDF capacity reports: hosts, memory, CPU, datastores, guest filesystems, VM count, and snapshot hygiene.

The files in this repository are a **fictional lab** (`vc-lab01`, `cluster-east`, `cluster-west`, `app-web-01`). They are not a customer environment.

## How many extracts

| Weekly snapshots | What you get |
|---|---|
| 1 | Point-in-time PDF: KPIs, host table, datastore and guest lists |
| 2–3 | Week-on-week deltas |
| 4 | Linear forecast (12 weeks ahead) on memory, CPU, and VM count |
| 8 | Enough history for the trend to be visible and for the forecast to stay in a sensible range |

This sample ships **8 Fridays**, 2026-09-04 through 2026-10-23. Forecast charts are drawn from week 4 onward. The included PDFs are the latest weekly report and the October monthly close.

## Run

```powershell
.\setup.bat
.\rvcap.bat ingest
.\rvcap.bat report --period weekly
.\rvcap.bat report --period monthly
```

`setup.bat` is once per machine. Later Fridays are only ingest plus the two report commands.

To regenerate the fictional workbooks:

```powershell
.\.venv\Scripts\python.exe scripts\make_sample_extracts.py
.\rvcap.bat ingest
```

Re-ingesting the same file is skipped. A replacement dump for the same vCenter and date overwrites that snapshot.

Expected filename: `RVTools_<env>_vCenter_<name>_YYYY-MM-DD.xlsx`.

Page 1 can show `assets/logos/left.png` and `assets/logos/right.png`. Those files are optional.

## What is kept

| Location | Role |
|---|---|
| `data/raw` | Friday xlsx files |
| `data/warehouse` | History, one parquet file per sheet per vCenter per date |
| `reports/weekly` | PDF for that Friday |
| `reports/monthly` | Month close = last snapshot in the month; trends use every week through that date |
