from __future__ import annotations

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
import pandas as pd
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from rvcap.charts import cluster_chart, cpu_chart, datastore_free_chart, memory_chart, snapshot_chart, vm_chart
from rvcap.insights import executive_summary, facts_payload, section_notes
from rvcap.metrics import Pack, datastore_table, guest_fs_hotspots, host_table, kpis
from rvcap.paths import logo_path, reports_monthly, reports_tmp, reports_weekly
from rvcap.warehouse import write_facts

NAVY = colors.HexColor("#1f3654")
BLUE = colors.HexColor("#2f5d8a")
PALE = colors.HexColor("#eef3f7")
AMBER_BG = colors.HexColor("#f7f1e3")
LINE = colors.HexColor("#d7dee6")
MUTED = colors.HexColor("#5c6b7a")
RED = colors.HexColor("#8c2f2f")
GREEN_FILL = colors.HexColor("#2d6a4f")
AMBER_FILL = colors.HexColor("#b8860b")
STATUS_FILL = {"GREEN": GREEN_FILL, "AMBER": AMBER_FILL, "RED": RED}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleX",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=NAVY,
            spaceAfter=2 * mm,
        ),
        "h2": ParagraphStyle(
            "H2X",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "BodyX",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#243040"),
        ),
        "muted": ParagraphStyle(
            "MutedX",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
        ),
        "callout": ParagraphStyle(
            "CalloutX",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#243040"),
            leftIndent=2 * mm,
        ),
        "kpi": ParagraphStyle(
            "KPIX",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=NAVY,
            alignment=TA_LEFT,
        ),
        "kpi_status": ParagraphStyle(
            "KPIStatusX",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "th": ParagraphStyle(
            "THX",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=colors.white,
            leading=9,
        ),
        "td": ParagraphStyle(
            "TDX",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#243040"),
        ),
    }


PAGE_W, PAGE_H = landscape(A4)


def _fit_logo(path: Path, max_w: float, max_h: float) -> tuple[float, float]:
    from PIL import Image as PILImage

    with PILImage.open(path) as image:
        width, height = image.size
    scale = min(max_w / width, max_h / height)
    return width * scale, height * scale


def _header_footer(period_label: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(12 * mm, PAGE_H - 8 * mm, "Capacity report · RVTools weekly snapshots")
        canvas.drawRightString(PAGE_W - 12 * mm, PAGE_H - 8 * mm, period_label)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(12 * mm, 6 * mm, "Numbers come from the parquet warehouse. Narrative is rule-based from the same facts.")
        canvas.drawRightString(PAGE_W - 12 * mm, 6 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _first_page_header(period_label: str):
    def draw(canvas, doc):
        canvas.saveState()
        left = logo_path("left")
        right = logo_path("right")
        max_h = 12 * mm
        if left:
            width, height = _fit_logo(left, 52 * mm, max_h)
            canvas.drawImage(str(left), 12 * mm, PAGE_H - 7 * mm - height, width=width, height=height, mask="auto")
        if right:
            width, height = _fit_logo(right, 58 * mm, max_h)
            canvas.drawImage(
                str(right),
                PAGE_W - 12 * mm - width,
                PAGE_H - 7 * mm - height,
                width=width,
                height=height,
                mask="auto",
            )
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(1.1)
        canvas.line(12 * mm, PAGE_H - 24 * mm, PAGE_W - 12 * mm, PAGE_H - 24 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(12 * mm, 6 * mm, "Numbers come from the parquet warehouse. Narrative is rule-based from the same facts.")
        canvas.drawRightString(PAGE_W - 12 * mm, 6 * mm, f"{period_label}  ·  Page {doc.page}")
        canvas.restoreState()

    return draw


def _kpi_row(items: list[tuple[str, str]], styles, status: str | None = None) -> Table:
    labels = [Paragraph(label, styles["muted"]) for label, _ in items]
    values = []
    for i, (_, value) in enumerate(items):
        is_status = status is not None and i == len(items) - 1
        values.append(Paragraph(value, styles["kpi_status"] if is_status else styles["kpi"]))
    table = Table([labels, values], colWidths=[45 * mm] * len(items))
    cmds = [
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.3, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if status:
        fill = STATUS_FILL.get(status.upper(), NAVY)
        last = len(items) - 1
        cmds.append(("BACKGROUND", (last, 1), (last, 1), fill))
        cmds.append(("TOPPADDING", (last, 1), (last, 1), 6))
        cmds.append(("BOTTOMPADDING", (last, 1), (last, 1), 6))
    table.setStyle(TableStyle(cmds))
    return table


def _callout(lines: list[str], styles) -> Table:
    text = "<br/>".join(f"• {line}" for line in lines)
    inner = Paragraph(text, styles["callout"])
    table = Table([[inner]], colWidths=[270 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), AMBER_BG),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9c89a")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _fmt(value, kind: str) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    if not kind:
        if isinstance(value, bool):
            return "Yes" if value else ""
        text = str(value).strip()
        return "" if text.lower() in {"nan", "nat", "none"} else text
    if kind == "int":
        return f"{int(round(float(value)))}"
    if kind == "pct":
        return f"{float(value):.0f}%"
    if kind == "gib":
        return f"{float(value):.0f}"
    if kind == "tib":
        return f"{float(value):.2f}"
    if kind == "ratio":
        return f"{float(value):.2f}"
    if kind == "delta":
        return f"{int(round(float(value))):+d}"
    if kind == "pct1":
        return f"{float(value):.1f}%"
    return str(value)


def _table(df, columns: list[tuple[str, str, str]], styles, col_widths: list[float]) -> Table | Paragraph:
    if df is None or df.empty:
        return Paragraph("No rows for this view.", styles["muted"])
    header = [Paragraph(title, styles["th"]) for title, _key, _kind in columns]
    body = []
    for _, row in df.iterrows():
        body.append([Paragraph(escape(_fmt(row[key], kind)), styles["td"]) for _title, key, kind in columns])
    data = [header] + body
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), PALE))
    table.setStyle(TableStyle(style_cmds))
    return table


def _image(path: Path | None, height_mm: float = 78) -> list:
    if path is None or not path.exists():
        return []
    return [Image(str(path), width=250 * mm, height=height_mm * mm), Spacer(1, 2 * mm)]


def _weekly_table(pack: Pack, styles):
    rows = []
    prev = None
    for point in pack.history:
        free = (1 - point.datastore_used_tib / point.datastore_capacity_tib) * 100 if point.datastore_capacity_tib else 0.0
        rows.append(
            {
                "Week": point.snapshot_date.isoformat(),
                "VMs": point.powered_on_vms,
                "dVMs": None if prev is None else point.powered_on_vms - prev.powered_on_vms,
                "RAM GiB": round(point.memory_used_gib),
                "dRAM": None if prev is None else round(point.memory_used_gib - prev.memory_used_gib),
                "CPU %": point.cpu_used_weighted_pct,
                "DS free %": free,
                "Snapshots": point.snapshot_vms,
            }
        )
        prev = point
    df = pd.DataFrame(rows)
    return _table(
        df,
        [
            ("Week", "Week", ""),
            ("VMs", "VMs", "int"),
            ("Δ VMs", "dVMs", "delta"),
            ("RAM GiB", "RAM GiB", "int"),
            ("Δ RAM", "dRAM", "delta"),
            ("CPU %", "CPU %", "pct1"),
            ("DS free %", "DS free %", "pct1"),
            ("Snapshots", "Snapshots", "int"),
        ],
        styles,
        [28 * mm, 22 * mm, 22 * mm, 28 * mm, 24 * mm, 22 * mm, 28 * mm, 28 * mm],
    )


def build_story(pack: Pack, period_kind: str, tmp: Path, styles) -> list:
    k = kpis(pack)
    notes = section_notes(pack)
    ht = host_table(pack)
    ds = datastore_table(pack)
    story = []
    subtitle = f"{period_kind.title()} close {pack.as_of.isoformat()}  ·  {', '.join(pack.environments) or 'environment n/a'}  ·  {', '.join(pack.vcenters) or 'vCenter n/a'}"
    story.append(Paragraph(pack.config.title, styles["title"]))
    story.append(Paragraph(subtitle, styles["muted"]))
    story.append(Spacer(1, 3 * mm))
    facts = facts_payload(pack)
    story.append(
        _kpi_row(
            [
                ("Powered-on VMs", str(k["powered_on_vms"])),
                ("Hosts", f"{k['hosts']} ({k['hosts_maintenance']} maint.)"),
                ("Memory used", f"{k['memory_used_pct']}%"),
                ("CPU weighted", f"{k['cpu_weighted_pct']}%"),
                ("Datastore free", f"{k['datastore_free_pct']}%"),
                ("Status", facts["status"]),
            ],
            styles,
            status=facts["status"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Executive summary", styles["h2"]))
    story.append(_callout(executive_summary(pack), styles))

    story.append(Paragraph("1. Host CPU and memory", styles["h2"]))
    story.append(
        Paragraph(
            f"Watch lines: {pack.config.thresholds.host_mem_warn_pct:.0f}% RAM and {pack.config.thresholds.host_cpu_warn_pct:.0f}% CPU. "
            "Critical is 80%. Balloon/swap is the real RAM distress signal.",
            styles["body"],
        )
    )
    cluster_img = cluster_chart(
        ht,
        tmp / "clusters.png",
        mem_warn=pack.config.thresholds.host_mem_warn_pct,
        mem_crit=pack.config.thresholds.host_mem_crit_pct,
    )
    story.extend(_image(cluster_img, height_mm=62))
    show = ht.head(pack.config.host_table_limit)
    story.append(
        _table(
            show,
            [
                ("Host", "Host", ""),
                ("Cluster", "Cluster", ""),
                ("Maint", "Maintenance", ""),
                ("CPU %", "CPU %", "pct"),
                ("Mem %", "Memory %", "pct"),
                ("Mem GiB", "Memory GiB", "gib"),
                ("Cores", "Cores", "int"),
                ("vCPU/core", "vCPU/core", "ratio"),
                ("VMs", "VMs", "int"),
            ],
            styles,
            [58 * mm, 52 * mm, 16 * mm, 18 * mm, 18 * mm, 22 * mm, 18 * mm, 22 * mm, 16 * mm],
        )
    )
    if len(ht) > pack.config.host_table_limit:
        story.append(Paragraph(f"Showing top {pack.config.host_table_limit} of {len(ht)} hosts by memory %.", styles["muted"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_callout(notes["hosts"], styles))

    mem_img = memory_chart(pack.history, pack.mem_forecast, tmp / "memory.png")
    cpu_img = cpu_chart(pack.history, pack.cpu_forecast, tmp / "cpu.png")
    story.append(PageBreak())
    story.append(Paragraph("2. Memory trend and forecast", styles["h2"]))
    story.extend(_image(mem_img))
    story.append(_callout(notes["memory"], styles))
    story.append(Paragraph("3. CPU trend and forecast", styles["h2"]))
    story.extend(_image(cpu_img))
    story.append(_callout(notes["cpu"], styles))
    if len(pack.history) >= 2:
        story.append(Paragraph("Weekly snapshots", styles["h2"]))
        story.append(_weekly_table(pack, styles))

    ds_img = datastore_free_chart(
        ds,
        tmp / "datastore.png",
        warn_pct=pack.config.thresholds.datastore_free_warn_pct,
        crit_pct=pack.config.thresholds.datastore_free_crit_pct,
    )
    story.append(PageBreak())
    story.append(Paragraph("4. Datastore space", styles["h2"]))
    story.append(
        Paragraph(
            "Host-local, depot and ISO datastores are omitted so 99% free scratch LUNs do not look like stranded capacity.",
            styles["body"],
        )
    )
    story.extend(_image(ds_img))
    story.append(
        _table(
            ds.head(pack.config.datastore_table_limit),
            [
                ("Datastore", "Datastore", ""),
                ("Cluster", "Cluster", ""),
                ("VMs", "VMs", "int"),
                ("Cap TiB", "Capacity TiB", "tib"),
                ("Prov TiB", "Provisioned TiB", "tib"),
                ("Used TiB", "In use TiB", "tib"),
                ("Free TiB", "Free TiB", "tib"),
                ("Free %", "Free %", "pct"),
            ],
            styles,
            [55 * mm, 50 * mm, 16 * mm, 22 * mm, 24 * mm, 22 * mm, 22 * mm, 18 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(_callout(notes["datastore"], styles))

    crit = guest_fs_hotspots(pack, pack.config.thresholds.guest_fs_crit_pct, limit=pack.config.guest_fs_table_limit)
    warn = guest_fs_hotspots(pack, pack.config.thresholds.guest_fs_warn_pct, limit=pack.config.guest_fs_table_limit)
    story.append(PageBreak())
    story.append(Paragraph("5. Guest filesystem hotspots", styles["h2"]))
    story.append(Paragraph("Critical ≤ 10% free. Warning ≤ 20% free. /boot and volumes under 1 GiB are hidden.", styles["body"]))
    story.append(Paragraph("Critical", styles["muted"]))
    story.append(
        _table(
            crit,
            [
                ("VM", "VM", ""),
                ("Disk", "Disk", ""),
                ("Cap GiB", "Capacity GiB", "gib"),
                ("Used GiB", "Consumed GiB", "gib"),
                ("Free GiB", "Free GiB", "gib"),
                ("Free %", "Free %", "pct"),
            ],
            styles,
            [55 * mm, 45 * mm, 25 * mm, 25 * mm, 25 * mm, 20 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Warning (includes critical)", styles["muted"]))
    warn_all = guest_fs_hotspots(pack, pack.config.thresholds.guest_fs_warn_pct)
    story.append(
        _table(
            warn,
            [
                ("VM", "VM", ""),
                ("Disk", "Disk", ""),
                ("Cap GiB", "Capacity GiB", "gib"),
                ("Used GiB", "Consumed GiB", "gib"),
                ("Free GiB", "Free GiB", "gib"),
                ("Free %", "Free %", "pct"),
            ],
            styles,
            [55 * mm, 45 * mm, 25 * mm, 25 * mm, 25 * mm, 20 * mm],
        )
    )
    if len(warn_all) > len(warn):
        story.append(
            Paragraph(
                f"Showing {len(warn)} of {len(warn_all)} guest filesystems at or below {pack.config.thresholds.guest_fs_warn_pct:.0f}% free.",
                styles["muted"],
            )
        )
    story.append(Spacer(1, 2 * mm))
    story.append(_callout(notes["guest_fs"], styles))

    vm_img = vm_chart(pack.history, pack.vm_forecast, tmp / "vms.png")
    story.append(Paragraph("6. Powered-on VM count", styles["h2"]))
    story.extend(_image(vm_img))
    story.append(_callout(notes["vms"], styles))
    if notes["hygiene"]:
        story.append(Paragraph("7. Hygiene", styles["h2"]))
        snap_img = snapshot_chart(pack.history, tmp / "snapshots.png")
        story.extend(_image(snap_img, height_mm=58))
        story.append(_callout(notes["hygiene"], styles))
    return story


def render_pdf(pack: Pack, period_kind: str, month: str | None = None) -> Path:
    reports_tmp().mkdir(parents=True, exist_ok=True)
    styles = _styles()
    if period_kind == "weekly":
        out_dir = reports_weekly()
        name = f"capacity_report_{pack.as_of.isoformat()}.pdf"
        label = f"Week of {pack.as_of.isoformat()}"
    else:
        out_dir = reports_monthly()
        stamp = month or pack.as_of.strftime("%Y-%m")
        name = f"capacity_report_{stamp}.pdf"
        label = f"Month {stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / name
    tmp = reports_tmp() / f"{period_kind}_{pack.as_of.isoformat()}"
    tmp.mkdir(parents=True, exist_ok=True)
    story = build_story(pack, period_kind, tmp, styles)
    has_logos = logo_path("left") is not None or logo_path("right") is not None
    doc = BaseDocTemplate(
        str(pdf_path),
        pagesize=landscape(A4),
        title=f"{pack.config.title} {label}",
        author="rvcap",
    )
    left, right, bottom = 12 * mm, 12 * mm, 12 * mm
    first_top = 28 * mm if has_logos else 16 * mm
    later_top = 16 * mm
    first_frame = Frame(left, bottom, PAGE_W - left - right, PAGE_H - first_top - bottom, id="first")
    later_frame = Frame(left, bottom, PAGE_W - left - right, PAGE_H - later_top - bottom, id="later")
    first_onpage = _first_page_header(label) if has_logos else _header_footer(label)
    doc.addPageTemplates(
        [
            PageTemplate(id="First", frames=[first_frame], onPage=first_onpage),
            PageTemplate(id="Later", frames=[later_frame], onPage=_header_footer(label)),
        ]
    )
    doc.build([NextPageTemplate("Later"), *story])
    write_facts(pdf_path, facts_payload(pack))
    return pdf_path
