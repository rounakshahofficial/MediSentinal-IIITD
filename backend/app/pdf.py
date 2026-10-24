"""Printable evidence-dossier rendering for human compliance review."""

from __future__ import annotations

import base64
import mimetypes
from datetime import date, datetime
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any

from app.schemas import CaseDossierRead

_MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


def _text(value: Any, fallback: str = "—") -> str:
    """Escape untrusted listing/reviewer content before inserting it into HTML."""
    if value is None or value == "":
        return fallback
    return escape(str(value), quote=True)


def _money(value: Decimal | None, places: int = 4) -> str:
    return "—" if value is None else f"INR {value:.{places}f}"


def _percent(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _timestamp(value: datetime | date | None) -> str:
    return "—" if value is None else escape(value.isoformat(), quote=True)


def _status_label(value: Any) -> str:
    raw = getattr(value, "value", value)
    return _text(str(raw).replace("_", " ").title())


def _list_items(items: list[str], empty: str = "No reasons recorded.") -> str:
    if not items:
        return f"<li>{escape(empty)}</li>"
    return "".join(f"<li>{_text(item)}</li>" for item in items)


def _evidence_file(screenshot_path: str | None, evidence_dir: Path) -> Path | None:
    """Resolve an allowlisted evidence image without permitting path traversal."""
    if not screenshot_path:
        return None
    filename = Path(screenshot_path).name
    if not filename:
        return None
    evidence_root = evidence_dir.resolve()
    candidate = (evidence_root / filename).resolve()
    try:
        candidate.relative_to(evidence_root)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.stat().st_size > _MAX_EVIDENCE_BYTES:
        return None
    mime, _ = mimetypes.guess_type(candidate.name)
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}:
        return None
    return candidate


def _evidence_data_uri(screenshot_path: str | None, evidence_dir: Path) -> str | None:
    """Embed an allowlisted evidence image as a self-contained HTML data URI."""
    candidate = _evidence_file(screenshot_path, evidence_dir)
    if candidate is None:
        return None
    mime, _ = mimetypes.guess_type(candidate.name)
    encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_dossier_html(dossier: CaseDossierRead, evidence_dir: Path) -> str:
    """Build an escaped, self-contained HTML dossier suitable for WeasyPrint."""
    listing = dossier.listing
    match = dossier.match
    reference = dossier.reference
    evidence_uri = _evidence_data_uri(listing.screenshot_path, evidence_dir)

    evidence_markup = (
        f'<img class="evidence" src="{evidence_uri}" alt="Captured listing evidence">'
        if evidence_uri
        else '<div class="missing">Evidence screenshot unavailable in configured storage.</div>'
    )

    reference_markup = (
        f"""
        <table>
          <tr><th>Ingredient</th><td>{_text(reference.ingredient)}</td><th>Strength</th><td>{_text(reference.strength)}</td></tr>
          <tr><th>Dosage form</th><td>{_text(reference.dosage_form)}</td><th>Unit</th><td>{_text(reference.unit)}</td></tr>
          <tr><th>Ceiling / unit</th><td>{_money(reference.ceiling_price_per_unit)}</td><th>GST</th><td>{_text(reference.gst_percent)}%</td></tr>
          <tr><th>Source order</th><td colspan="3">{_text(reference.source_order)}</td></tr>
          <tr><th>Effective from</th><td>{_timestamp(reference.effective_from)}</td><th>Version</th><td>{_text(reference.version)}</td></tr>
        </table>
        """
        if reference
        else '<div class="warning">No reference row was resolved. Calculation remains withheld pending verification.</div>'
    )

    field_rows = "".join(
        f"""
        <tr>
          <td>{_text(field.replace('_', ' ').title())}</td>
          <td>{_text(audit.raw_text)}</td>
          <td>{_text(audit.normalized_value)}</td>
          <td>{_text(audit.rule_applied)}</td>
        </tr>
        """
        for field, audit in dossier.raw_audit.items()
    ) or '<tr><td colspan="4">No parsed-field audit rows recorded.</td></tr>'

    prior_rows = "".join(
        f"""
        <tr>
          <td>#{prior.case_id}</td>
          <td>{_timestamp(prior.observed_at)}</td>
          <td>{_money(prior.observed_per_unit)}</td>
          <td>{_percent(prior.discrepancy_percent)}</td>
          <td>{_status_label(prior.status)}</td>
        </tr>
        """
        for prior in dossier.prior_cases
    ) or '<tr><td colspan="5">No earlier discrepancy observations recorded for this product and site.</td></tr>'

    review_rows = "".join(
        f"""
        <tr>
          <td>{_timestamp(review.created_at)}</td>
          <td>{_status_label(review.action)}</td>
          <td>{_text(review.reviewer)}</td>
          <td>{_text(review.note, 'No note supplied.')}</td>
        </tr>
        """
        for review in dossier.reviews
    ) or '<tr><td colspan="4">No human review actions recorded yet.</td></tr>'

    match_markup = (
        f"""
        <table>
          <tr><th>Status</th><td>{_status_label(match.status)}</td><th>Confidence</th><td>{match.confidence * 100:.1f}%</td></tr>
          <tr><th>Ingredient</th><td>{_text(match.parsed_ingredient)}</td><th>Strength</th><td>{_text(match.parsed_strength)}</td></tr>
          <tr><th>Dosage form</th><td>{_text(match.parsed_form)}</td><th>Units in pack</th><td>{_text(match.units_in_pack)}</td></tr>
        </table>
        <h3>Match reasons</h3><ul>{_list_items(match.reasons)}</ul>
        """
        if match
        else '<div class="warning">No deterministic match record is attached.</div>'
    )

    sample_notice = ""
    if reference and any(
        token in f"{reference.source_order} {reference.version}".upper()
        for token in ("SAMPLE", "REPLACE", "UNVERIFIED")
    ):
        sample_notice = (
            '<div class="warning"><strong>Demo reference:</strong> This row is marked sample/unverified. '
            "Replace it with a verified official NPPA order before formal review.</div>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MediSentinel Case #{dossier.id} Evidence Dossier</title>
  <style>
    @page {{ size: A4; margin: 15mm 14mm 17mm; @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #64748b; }} }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: Arial, sans-serif; color: #0f172a; font-size: 9.2pt; line-height: 1.4; }}
    h1 {{ margin: 0 0 3mm; color: #1d4ed8; font-size: 20pt; }}
    h2 {{ margin: 6mm 0 2mm; border-bottom: 1px solid #cbd5e1; padding-bottom: 1.5mm; color: #1e293b; font-size: 12pt; }}
    h3 {{ margin: 3mm 0 1mm; font-size: 9.5pt; }}
    p {{ margin: 1mm 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 2mm 0; break-inside: avoid; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 2mm; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ background: #f1f5f9; color: #334155; text-align: left; font-weight: 600; }}
    ul {{ margin: 1mm 0 1mm 5mm; padding-left: 3mm; }}
    .header {{ border-left: 4px solid #2563eb; padding-left: 4mm; }}
    .status {{ display: inline-block; padding: 1mm 2.2mm; border-radius: 8mm; background: #fef2f2; color: #b91c1c; font-weight: 700; }}
    .meta {{ color: #475569; }}
    .notice {{ margin-top: 3mm; padding: 3mm; border: 1px solid #bfdbfe; background: #eff6ff; color: #1e3a8a; }}
    .warning {{ margin: 2mm 0; padding: 3mm; border: 1px solid #fcd34d; background: #fffbeb; color: #78350f; }}
    .missing {{ padding: 15mm 3mm; border: 1px dashed #94a3b8; background: #f8fafc; text-align: center; color: #64748b; }}
    .evidence {{ display: block; max-width: 100%; max-height: 142mm; margin: 2mm auto; border: 1px solid #cbd5e1; object-fit: contain; }}
    .formula {{ padding: 3mm; border-left: 3px solid #2563eb; background: #f8fafc; font-family: monospace; overflow-wrap: anywhere; }}
    .metric {{ font-family: monospace; font-weight: 700; }}
    .review-options {{ margin-top: 2mm; padding: 2.5mm; background: #f8fafc; color: #475569; }}
    .small {{ font-size: 8pt; color: #64748b; }}
  </style>
</head>
<body>
  <header class="header">
    <h1>MediSentinel Evidence Dossier</h1>
    <p><strong>Case #{dossier.id}</strong> &nbsp; <span class="status">{_status_label(dossier.status)}</span></p>
    <p class="meta">Generated for human compliance review · Case created {_timestamp(dossier.created_at)}</p>
  </header>

  <div class="notice"><strong>Advisory notice:</strong> This dossier surfaces a potential discrepancy for human verification. It is not a legal determination.</div>
  {sample_notice}

  <h2>1. Listing details and evidence</h2>
  <table>
    <tr><th>Pharmacy</th><td>{_text(listing.site)}</td><th>Product</th><td>{_text(listing.product_name)}</td></tr>
    <tr><th>Raw composition</th><td>{_text(listing.composition_raw)}</td><th>Raw pack size</th><td>{_text(listing.pack_size_raw)}</td></tr>
    <tr><th>Pack MRP</th><td>{_money(listing.mrp, 2)}</td><th>Selling price</th><td>{_money(listing.selling_price, 2)}</td></tr>
    <tr><th>Observed at</th><td>{_timestamp(listing.observed_at)}</td><th>Evidence file</th><td>{_text(listing.screenshot_path)}</td></tr>
    <tr><th>Listing URL</th><td colspan="3">{_text(listing.url)}</td></tr>
  </table>
  {evidence_markup}

  <h2>2. Deterministic parse and match</h2>
  {match_markup}
  <table>
    <thead><tr><th>Field</th><th>Raw text</th><th>Normalized value</th><th>Rule applied</th></tr></thead>
    <tbody>{field_rows}</tbody>
  </table>

  <h2>3. NPPA reference</h2>
  {reference_markup}

  <h2>4. Calculation proof</h2>
  <table>
    <tr><th>Observed / unit</th><td class="metric">{_money(dossier.observed_per_unit)}</td><th>Selling / unit</th><td class="metric">{_money(dossier.selling_per_unit)}</td></tr>
    <tr><th>Allowed / unit</th><td class="metric">{_money(dossier.allowed_per_unit)}</td><th>Potential difference</th><td class="metric">{_percent(dossier.discrepancy_percent)}</td></tr>
    <tr><th>Reference version</th><td>{_text(dossier.reference_version)}</td><th>Priority score</th><td>{dossier.priority_score:.1f} / 100</td></tr>
  </table>
  <div class="formula">{_text(dossier.formula, 'Calculation withheld because required matching or pack fields need verification.')}</div>
  <h3>Calculation reasons</h3><ul>{_list_items(dossier.calculation_reasons)}</ul>
  <h3>Priority reasons</h3><ul>{_list_items(dossier.priority_reasons)}</ul>

  <h2>5. Recurrence and observation history</h2>
  <p>Group: <strong>{_text(dossier.recurrence_group_key)}</strong> · Active observations: {dossier.recurrence_count} · Recurrent: {_text('Yes' if dossier.is_recurrent else 'No')}</p>
  <table>
    <thead><tr><th>Case</th><th>Observed at</th><th>Observed / unit</th><th>Potential difference</th><th>Status</th></tr></thead>
    <tbody>{prior_rows}</tbody>
  </table>

  <h2>6. Human review actions</h2>
  <table>
    <thead><tr><th>Timestamp</th><th>Action</th><th>Reviewer</th><th>Audit note</th></tr></thead>
    <tbody>{review_rows}</tbody>
  </table>
  <div class="review-options"><strong>Reviewer workflow:</strong> Confirm for review · Dismiss · Request more evidence. Every action must be recorded with reviewer identity and an audit note.</div>

  <p class="small">MediSentinel · India medicine-price compliance intelligence prototype · One medicine family · Permitted online pharmacy listings only.</p>
</body>
</html>"""


def _fallback_text(value: Any) -> str:
    """Keep the native-library fallback compatible with FPDF's built-in font."""
    raw = "—" if value is None or value == "" else str(value)
    return raw.encode("latin-1", errors="replace").decode("latin-1")


def _render_with_fpdf_fallback(dossier: CaseDossierRead, evidence_dir: Path) -> bytes:
    """Keep downloads operational when the host image lacks WeasyPrint native libraries.

    WeasyPrint remains the primary renderer. This deterministic fallback mirrors the same
    dossier fields and supports the stored PNG/JPEG/WebP/SVG evidence formats.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover - dependency is pinned in requirements
        raise RuntimeError("No PDF renderer is available.") from exc

    pdf = FPDF(format="A4")
    pdf.set_margins(14, 13, 14)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(f"MediSentinel Case #{dossier.id} Evidence Dossier")
    pdf.set_author("MediSentinel")
    pdf.add_page()

    def heading(text: str, level: int = 2) -> None:
        pdf.ln(2 if level == 2 else 1)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 14 if level == 1 else 11)
        pdf.set_text_color(29, 78, 216 if level == 1 else 90)
        pdf.multi_cell(0, 7 if level == 1 else 6, _fallback_text(text))
        pdf.set_text_color(15, 23, 42)

    def line(label: str, value: Any) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(0, 5, _fallback_text(f"{label}: {value if value not in (None, '') else '—'}"))

    def bullets(items: list[str], empty: str) -> None:
        pdf.set_font("Helvetica", "", 8.5)
        for item in items or [empty]:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 5, _fallback_text(f"- {item}"))

    heading("MediSentinel Evidence Dossier", level=1)
    line("Case", f"#{dossier.id}")
    line("Status", _status_label(dossier.status).replace("&amp;", "&"))
    line("Created", dossier.created_at.isoformat())
    pdf.set_fill_color(239, 246, 255)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        5,
        _fallback_text(
            "Advisory notice: This dossier surfaces a potential discrepancy for human "
            "verification. It is not a legal determination."
        ),
        fill=True,
    )

    heading("1. Listing details and evidence")
    listing = dossier.listing
    line("Pharmacy", listing.site)
    line("Product", listing.product_name)
    line("Raw composition", listing.composition_raw)
    line("Raw pack size", listing.pack_size_raw)
    line("Pack MRP", _money(listing.mrp, 2))
    line("Selling price", _money(listing.selling_price, 2))
    line("Observed at", listing.observed_at.isoformat())
    line("Listing URL", listing.url)

    evidence = _evidence_file(listing.screenshot_path, evidence_dir)
    if evidence is not None:
        try:
            available_height = max(35.0, 270.0 - pdf.get_y())
            image_height = min(105.0, available_height)
            pdf.image(str(evidence), x=20, w=170, h=image_height, keep_aspect_ratio=True)
            pdf.ln(2)
        except Exception:
            line("Evidence", f"Stored at {listing.screenshot_path}; preview unavailable.")
    else:
        line("Evidence", "Screenshot unavailable in configured storage.")

    heading("2. Deterministic parse and match")
    if dossier.match:
        match = dossier.match
        line("Match status", match.status)
        line("Confidence", f"{match.confidence * 100:.1f}%")
        line("Ingredient", match.parsed_ingredient)
        line("Strength", match.parsed_strength)
        line("Dosage form", match.parsed_form)
        line("Units in pack", match.units_in_pack)
        bullets(match.reasons, "No match reasons recorded.")
    else:
        line("Match", "No deterministic match record attached.")
    for field, audit in dossier.raw_audit.items():
        line(
            field.replace("_", " ").title(),
            f"raw={audit.raw_text!r}; normalized={audit.normalized_value!r}; "
            f"rule={audit.rule_applied or 'n/a'}",
        )

    heading("3. NPPA reference")
    if dossier.reference:
        reference = dossier.reference
        line("Formulation", f"{reference.ingredient} {reference.strength} {reference.dosage_form}")
        line("Ceiling per unit", _money(reference.ceiling_price_per_unit))
        line("GST", f"{reference.gst_percent}%")
        line("Source order", reference.source_order)
        line("Effective from", reference.effective_from.isoformat())
        line("Version", reference.version)
    else:
        line("Reference", "No reference row resolved; calculation remains withheld.")

    heading("4. Calculation proof")
    line("Observed per unit", _money(dossier.observed_per_unit))
    line("Selling per unit", _money(dossier.selling_per_unit))
    line("Allowed per unit", _money(dossier.allowed_per_unit))
    line("Potential difference", _percent(dossier.discrepancy_percent))
    line("Reference version", dossier.reference_version)
    line("Priority score", f"{dossier.priority_score:.1f} / 100")
    line(
        "Formula",
        dossier.formula
        or "Calculation withheld because required matching or pack fields need verification.",
    )
    bullets(dossier.calculation_reasons, "No calculation reasons recorded.")
    bullets(dossier.priority_reasons, "No priority reasons recorded.")

    heading("5. Recurrence and observation history")
    line("Recurrence group", dossier.recurrence_group_key)
    line("Active observations", dossier.recurrence_count)
    line("Recurrent", "Yes" if dossier.is_recurrent else "No")
    if dossier.prior_cases:
        for prior in dossier.prior_cases:
            line(
                f"Prior case #{prior.case_id}",
                f"{prior.observed_at.isoformat()} | observed {_money(prior.observed_per_unit)} | "
                f"potential difference {_percent(prior.discrepancy_percent)} | {prior.status}",
            )
    else:
        line("History", "No earlier observations recorded for this product and site.")

    heading("6. Human review actions")
    if dossier.reviews:
        for review in dossier.reviews:
            line(
                review.action.replace("_", " ").title(),
                f"{review.created_at.isoformat()} | {review.reviewer} | "
                f"{review.note or 'No note supplied.'}",
            )
    else:
        line("Review log", "No human review actions recorded yet.")
    line("Reviewer workflow", "Confirm for review | Dismiss | Request more evidence")

    result = pdf.output()
    return bytes(result)


def render_dossier_pdf(dossier: CaseDossierRead, evidence_dir: Path) -> bytes:
    """Render an A4 dossier with WeasyPrint, with a native-library-safe fallback."""
    # Avoid importing WeasyPrint on lean Linux images that clearly lack Pango; its
    # import-time diagnostic otherwise writes directly to stdout for every download.
    import ctypes.util
    import sys

    if sys.platform.startswith("linux") and not ctypes.util.find_library("pango-1.0"):
        return _render_with_fpdf_fallback(dossier, evidence_dir)

    html = build_dossier_html(dossier, evidence_dir)
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        return _render_with_fpdf_fallback(dossier, evidence_dir)

    try:
        result = HTML(string=html, base_url=str(evidence_dir.resolve())).write_pdf()
    except (ImportError, OSError):
        return _render_with_fpdf_fallback(dossier, evidence_dir)
    except Exception as exc:
        raise RuntimeError("WeasyPrint failed while rendering the dossier.") from exc
    if not isinstance(result, bytes):
        raise RuntimeError("WeasyPrint did not return PDF bytes.")
    return result
