"""Generate deterministic SVG evidence screenshots in storage/evidence/ from cached scans."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402

SITE_ACCENTS = {
    "1mg": "#e11d48",
    "pharmeasy": "#0d9488",
    "netmeds": "#2563eb",
}


def render_evidence_svg(entry: dict[str, object]) -> str:
    site = str(entry.get("site", "pharmacy")).lower()
    accent = SITE_ACCENTS.get(site, "#334155")
    url = html.escape(str(entry.get("url", "")))
    title = html.escape(str(entry.get("product_name", "")))
    comp = html.escape(str(entry.get("composition_raw", "N/A")))
    pack = html.escape(str(entry.get("pack_size_raw", "N/A")))
    mrp = html.escape(str(entry.get("mrp", "N/A")))
    sell = html.escape(str(entry.get("selling_price", "N/A")))
    obs = html.escape(str(entry.get("observed_at", "")))
    mfr = html.escape(str(entry.get("manufacturer", "")))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="440" viewBox="0 0 800 440">
  <rect width="800" height="440" rx="12" fill="#f8fafc" stroke="#cbd5e1" stroke-width="2"/>
  <rect width="800" height="46" rx="12" fill="#e2e8f0"/>
  <rect y="34" width="800" height="12" fill="#e2e8f0"/>
  <circle cx="24" cy="23" r="6" fill="#ef4444"/>
  <circle cx="44" cy="23" r="6" fill="#f59e0b"/>
  <circle cx="64" cy="23" r="6" fill="#22c55e"/>
  <rect x="90" y="10" width="686" height="26" rx="6" fill="#ffffff" stroke="#cbd5e1"/>
  <text x="104" y="28" font-family="monospace" font-size="12" fill="#334155">{url}</text>

  <rect x="28" y="68" width="744" height="344" rx="10" fill="#ffffff" stroke="#e2e8f0" stroke-width="1.5"/>
  <rect x="48" y="88" width="128" height="28" rx="6" fill="{accent}"/>
  <text x="112" y="107" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="13" fill="#ffffff">{site.upper()}</text>
  <text x="748" y="106" text-anchor="end" font-family="monospace" font-size="12" fill="#64748b">Captured: {obs}</text>

  <text x="48" y="152" font-family="sans-serif" font-weight="bold" font-size="24" fill="#0f172a">{title}</text>
  <text x="48" y="176" font-family="sans-serif" font-size="13" fill="#64748b">{mfr}</text>

  <line x1="48" y1="196" x2="752" y2="196" stroke="#e2e8f0"/>

  <text x="48" y="228" font-family="sans-serif" font-weight="bold" font-size="13" fill="#475569">SALT COMPOSITION (RAW):</text>
  <text x="245" y="228" font-family="monospace" font-size="14" fill="#0f172a">{comp}</text>

  <text x="48" y="262" font-family="sans-serif" font-weight="bold" font-size="13" fill="#475569">PACK SIZE (RAW):</text>
  <text x="245" y="262" font-family="monospace" font-size="14" fill="#0f172a">{pack}</text>

  <rect x="48" y="290" width="330" height="94" rx="8" fill="#f1f5f9" stroke="#cbd5e1"/>
  <text x="68" y="320" font-family="sans-serif" font-size="13" fill="#475569">Listed MRP (incl. of all taxes): INR {mrp}</text>
  <text x="68" y="356" font-family="sans-serif" font-weight="bold" font-size="22" fill="#0f172a">Selling Price: INR {sell}</text>

  <rect x="404" y="290" width="348" height="94" rx="8" fill="#fffbeb" stroke="#fde68a"/>
  <text x="424" y="322" font-family="sans-serif" font-weight="bold" font-size="12" fill="#92400e">EVIDENCE DOSSIER SNAPSHOT</text>
  <text x="424" y="346" font-family="sans-serif" font-size="12" fill="#78350f">Sample cached capture for human compliance</text>
  <text x="424" y="366" font-family="sans-serif" font-size="12" fill="#78350f">verification. Never an automated legal finding.</text>
</svg>
"""


def main() -> None:
    settings = get_settings()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for json_file in sorted(settings.cached_scans_dir.glob("*.json")):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        for entry in data.get("listings", []):
            mount_path = entry.get("screenshot_path")
            if not isinstance(mount_path, str) or not mount_path.startswith("/storage/evidence/"):
                continue
            filename = mount_path.removeprefix("/storage/evidence/")
            out_path = settings.evidence_dir / filename
            out_path.write_text(render_evidence_svg(entry), encoding="utf-8")
            written += 1
    print(f"Generated {written} sample evidence SVG files in {settings.evidence_dir}")


if __name__ == "__main__":
    main()
