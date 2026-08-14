"""Test metadata extraction on a sample of reports."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.metadata import extract_metadata
from core.parser import clean_text, parse_report, get_report_files


REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "故障报告")
SAMPLE_SIZE = 20


def main():
    files = get_report_files(REPORT_DIR)
    sampled = random.sample(files, min(SAMPLE_SIZE, len(files)))

    for file_path in sampled:
        text = clean_text(parse_report(file_path))
        meta = extract_metadata(file_path, text)
        print("-" * 80)
        print(f"File: {meta['report_name']}")
        print(f"  year:     {meta.get('year')}")
        print(f"  quarter:  {meta.get('quarter')}")
        print(f"  month:    {meta.get('month')}")
        print(f"  date:     {meta.get('date')}")
        print(f"  province: {meta.get('province')}")
        print(f"  voltage:  {meta.get('voltage')}")
        print(f"  line:     {meta.get('line')}")
        print(f"  fault:    {meta.get('fault_type')}")
        print(f"  towers:   {meta.get('towers')[:5]}")
        print(f"  trips:    {meta.get('trip_times')[:3]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
