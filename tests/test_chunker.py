"""Test chunking on a sample of reports."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import CHUNK_MAX_CHARS
from core.chunker import chunk_report
from core.parser import clean_text, parse_report, get_report_files


REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "故障报告")
SAMPLE_SIZE = 10


def main():
    files = get_report_files(REPORT_DIR)
    sampled = random.sample(files, min(SAMPLE_SIZE, len(files)))

    total_chunks = 0
    oversized = 0
    for file_path in sampled:
        text = clean_text(parse_report(file_path))
        chunks = chunk_report(file_path, text)
        total_chunks += len(chunks)
        for chunk in chunks:
            length = len(chunk["text"])
            if length > CHUNK_MAX_CHARS:
                oversized += 1
        print(f"{os.path.basename(file_path)}: {len(chunks)} chunks")
        for i, chunk in enumerate(chunks):
            print(f"  [{i}] type={chunk['metadata']['chunk_type']}, len={len(chunk['text'])}")

    print(f"\nTotal chunks: {total_chunks}")
    print(f"Oversized chunks (>{CHUNK_MAX_CHARS} chars): {oversized}")
    return 1 if oversized > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
