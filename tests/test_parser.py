"""Test parser by sampling reports and verifying non-empty text extraction."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.parser import clean_text, parse_report, get_report_files


REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "故障报告")
SAMPLE_SIZE = 20


def main():
    files = get_report_files(REPORT_DIR)
    print(f"Total report files: {len(files)}")

    # Ensure coverage of all formats
    by_ext = {}
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        by_ext.setdefault(ext, []).append(f)

    sampled = []
    for ext, group in by_ext.items():
        picked = random.sample(group, min(5, len(group)))
        sampled.extend(picked)

    # Fill remaining sample size randomly if needed
    remaining = SAMPLE_SIZE - len(sampled)
    if remaining > 0:
        extras = [f for f in files if f not in sampled]
        sampled.extend(random.sample(extras, min(remaining, len(extras))))

    random.shuffle(sampled)

    success = 0
    failures = []
    for file_path in sampled:
        try:
            text = parse_report(file_path)
            text = clean_text(text)
            length = len(text)
            status = "OK" if length > 0 else "EMPTY"
            if length > 0:
                success += 1
            else:
                failures.append(file_path)
            print(f"[{status}] {os.path.basename(file_path)}: {length} chars")
        except Exception as exc:
            failures.append(file_path)
            print(f"[FAIL] {os.path.basename(file_path)}: {exc}")

    print(f"\nSuccess: {success}/{len(sampled)}")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
