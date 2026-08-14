"""Multi-format fault report parser.

Supports PDF, DOCX, DOC, and WPS files. PDF is parsed with pdfplumber,
DOCX with python-docx, and DOC/WPS with LibreOffice soffice headless
conversion to plain text.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import pdfplumber
from docx import Document


def parse_report(file_path: str) -> str:
    """Extract text from a fault report file.

    Args:
        file_path: Path to the report file.

    Returns:
        Extracted text as a single string. Empty string if extraction fails.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Report file not found: {file_path}")

    ext = path.suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(path)
    if ext == ".docx":
        return _parse_docx(path)
    if ext in {".doc", ".wps"}:
        return _parse_doc_wps(path)

    raise ValueError(f"Unsupported file format: {ext}")


def _parse_pdf(path: Path) -> str:
    """Extract text from PDF using pdfplumber."""
    parts = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _parse_docx(path: Path) -> str:
    """Extract text from DOCX using python-docx."""
    doc = Document(str(path))
    parts = []
    for para in doc.paragraphs:
        if para.text:
            parts.append(para.text)
    return "\n".join(parts)


def _parse_doc_wps(path: Path) -> str:
    """Extract text from old DOC/WPS using LibreOffice soffice."""
    if shutil.which("soffice") is None:
        raise RuntimeError("LibreOffice 'soffice' not found in PATH")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "txt:Text",
            "--outdir",
            tmpdir,
            str(path),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"LibreOffice conversion failed for {path}: {exc.stderr.decode('utf-8', errors='ignore')}"
            ) from exc

        # LibreOffice outputs basename.txt
        txt_name = path.stem + ".txt"
        txt_path = Path(tmpdir) / txt_name
        if not txt_path.exists():
            return ""

        try:
            text = txt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive
            text = txt_path.read_text(encoding="gbk", errors="ignore")

    return text


def get_report_files(report_dir: str, extensions: Optional[set] = None) -> list[str]:
    """List all report files under a directory."""
    if extensions is None:
        extensions = {".pdf", ".docx", ".doc", ".wps"}

    files = []
    for root, _, filenames in os.walk(report_dir):
        for name in filenames:
            if Path(name).suffix.lower() in extensions:
                files.append(os.path.join(root, name))
    return sorted(files)


def clean_text(text: str) -> str:
    """Normalize whitespace in extracted text."""
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
