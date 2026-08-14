"""Convert WPS reports to DOCX and move originals to a backup directory.

One-off / reusable ingestion utility. After conversion, the report directory
contains only DOCX files, so indexing relies solely on python-docx (pure
Python, no LibreOffice dependency). Originals are preserved in the backup
directory, which lives OUTSIDE the report directory because get_report_files
scans recursively.

Usage:
    python3 scripts/convert_wps.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "故障报告"
BACKUP_DIR = PROJECT_ROOT / "故障报告_WPS备份"
CONVERT_TIMEOUT = 300  # large WPS files (100+ pages) need well over 60s

MAC_SOFFICE_FALLBACK = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def find_soffice() -> str:
    """Locate the soffice executable."""
    exe = shutil.which("soffice")
    if exe:
        return exe
    if Path(MAC_SOFFICE_FALLBACK).exists():
        return MAC_SOFFICE_FALLBACK
    raise RuntimeError(
        "LibreOffice 'soffice' not found in PATH or default install location"
    )


def convert_one(soffice: str, wps_path: Path) -> Path:
    """Convert a single WPS file to DOCX in the report directory.

    Returns the generated DOCX path. Idempotent: skips conversion if the
    DOCX already exists.
    """
    docx_path = wps_path.with_suffix(".docx")
    if docx_path.exists():
        print(f"[SKIP] DOCX already exists: {docx_path.name}")
        return docx_path

    subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(REPORT_DIR),
            str(wps_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=CONVERT_TIMEOUT,
    )
    if not docx_path.exists():
        raise RuntimeError(f"Conversion produced no output: {docx_path.name}")
    return docx_path


def main() -> int:
    wps_files = sorted(REPORT_DIR.glob("*.wps"))
    if not wps_files:
        print("No WPS files found in report directory.")
        return 0

    soffice = find_soffice()
    print(f"Using soffice: {soffice}")
    print(f"Found {len(wps_files)} WPS file(s) to convert.\n")

    succeeded = []
    failed = []

    for wps_path in wps_files:
        print(f"[CONVERT] {wps_path.name} ...")
        try:
            docx_path = convert_one(soffice, wps_path)
        except subprocess.TimeoutExpired:
            print(f"[FAIL] {wps_path.name}: conversion timed out after {CONVERT_TIMEOUT}s")
            failed.append(wps_path.name)
            continue
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"[FAIL] {wps_path.name}: {exc}")
            failed.append(wps_path.name)
            continue

        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.move(str(wps_path), str(BACKUP_DIR / wps_path.name))
        print(f"[OK] {docx_path.name} (original moved to {BACKUP_DIR.name}/)")
        succeeded.append(docx_path.name)

    print(f"\nDone. Converted: {len(succeeded)}, Failed: {len(failed)}")
    if failed:
        print("Failed files remain in the report directory:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
