"""Static file server for original fault reports.

Serves reports by report_id so generated answers can link back to source
files: GET /reports/{report_id}

Uses only the Python standard library (no new dependencies).

Usage:
    python3 src/file_server/server.py
"""

import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import FILE_SERVER_HOST, FILE_SERVER_PORT, REPORT_DIR
from core.metadata import compute_report_id
from core.parser import get_report_files

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".wps": "application/octet-stream",
}

# Word 文档转 PDF 的持久缓存目录（项目根目录下，不会被系统清理）
PDF_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pdf_cache",
)
WORD_EXTS = {".doc", ".docx", ".wps"}
_convert_lock = threading.Lock()

_report_index: dict[str, str] = {}


def convert_to_pdf(file_path: str, report_id: str) -> str | None:
    """Convert a Word report to PDF cached by report_id.

    Returns the cached PDF path, or None if conversion failed.
    First hit converts on demand; subsequent hits read the cache directly.
    """
    cached = os.path.join(PDF_CACHE_DIR, f"{report_id}.pdf")
    if os.path.exists(cached):
        return cached

    # soffice 多实例并发会抢用户配置锁，串行化转换
    with _convert_lock:
        if os.path.exists(cached):
            return cached
        os.makedirs(PDF_CACHE_DIR, exist_ok=True)
        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", PDF_CACHE_DIR, file_path],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            produced = os.path.join(
                PDF_CACHE_DIR, os.path.splitext(os.path.basename(file_path))[0] + ".pdf"
            )
            os.replace(produced, cached)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            print(f"[file_server] PDF conversion failed for {file_path}: {exc}")
            return None
    return cached


def build_index() -> None:
    """Build report_id -> file path mapping by scanning the report directory."""
    global _report_index
    index = {}
    for file_path in get_report_files(REPORT_DIR):
        index[compute_report_id(file_path)] = file_path
    _report_index = index


def lookup(report_id: str) -> str | None:
    """Look up file path by report_id, rebuilding the index once on miss."""
    path = _report_index.get(report_id)
    if path and os.path.exists(path):
        return path
    build_index()
    path = _report_index.get(report_id)
    if path and os.path.exists(path):
        return path
    return None


class ReportHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if len(parts) == 2 and parts[0] == "reports":
            self._serve_report(parts[1])
        elif len(parts) == 3 and parts[0] == "reports" and parts[2] == "raw":
            self._serve_report_raw(parts[1])
        elif parsed.path == "/health":
            self._send_text(200, f"ok, {len(_report_index)} reports indexed")
        else:
            self._send_text(404, "not found")

    def _serve_report(self, report_id: str) -> None:
        """Serve an HTML wrapper page whose <title> is the real filename.

        Browsers show the PDF's internal /Title metadata (or the URL's last
        segment) as the tab title, and many reports carry stale/wrong /Title
        from the original Word document properties. Wrapping the PDF in a
        page makes the browser show the real filename instead.
        """
        file_path = lookup(report_id)
        if file_path is None:
            self._send_text(404, "report not found")
            return

        # Escape & < > so the filename can't break the HTML markup
        title = os.path.basename(file_path)
        title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = (
            "<!DOCTYPE html>\n"
            "<html>\n<head>\n"
            '<meta charset="utf-8">\n'
            f"<title>{title}</title>\n"
            "<style>html,body{margin:0;height:100%}iframe{width:100%;height:100%;border:none}</style>\n"
            "</head>\n<body>\n"
            f'<iframe src="/reports/{report_id}/raw"></iframe>\n'
            "</body>\n</html>\n"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_report_raw(self, report_id: str) -> None:
        file_path = lookup(report_id)
        if file_path is None:
            self._send_text(404, "report not found")
            return

        ext = os.path.splitext(file_path)[1].lower()
        filename = os.path.basename(file_path)

        # Word 文档：优先返回缓存/即时转换的 PDF（浏览器可直接打开），
        # 转换失败时兜底为原始文档下载
        if ext in WORD_EXTS:
            pdf_path = convert_to_pdf(file_path, report_id)
            if pdf_path is not None:
                file_path = pdf_path
                ext = ".pdf"
                filename = os.path.splitext(filename)[0] + ".pdf"

        content_type = MIME_TYPES.get(ext, "application/octet-stream")

        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError:
            self._send_text(500, "failed to read report file")
            return

        # PDF opens inline in browser; other formats download with original name
        encoded_name = urllib.parse.quote(filename)
        disposition = "inline" if ext == ".pdf" else "attachment"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            f"{disposition}; filename*=UTF-8''{encoded_name}",
        )
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write("[file_server] " + format % args + "\n")


def main() -> None:
    build_index()
    print(f"Indexed {len(_report_index)} reports from {REPORT_DIR}")
    server = ThreadingHTTPServer((FILE_SERVER_HOST, FILE_SERVER_PORT), ReportHandler)
    print(f"File server listening on http://{FILE_SERVER_HOST}:{FILE_SERVER_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
