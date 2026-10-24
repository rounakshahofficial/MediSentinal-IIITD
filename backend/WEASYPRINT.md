# WeasyPrint runtime dependencies

`GET /cases/{id}/dossier.pdf` uses the Python `weasyprint` package from
`requirements.txt`. WeasyPrint also requires native Pango/Cairo libraries in the
host image; `pip` does not install these operating-system packages.

Typical Debian/Ubuntu setup:

```bash
sudo apt-get update
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0
```

Typical macOS setup:

```bash
brew install pango
```

Then install Python dependencies and verify the PDF tests:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/test_step7_pdf.py -v
```

The application imports WeasyPrint lazily. On lean Linux preview images where Pango is
absent, dossier downloads remain operational through a deterministic `fpdf2` fallback
that carries the same listing, reference, formula, evidence, history, and review fields.
Install Pango in production to use the primary HTML/CSS WeasyPrint layout.
