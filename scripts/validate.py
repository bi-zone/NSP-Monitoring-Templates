#!/usr/bin/env python3
"""Validate our export subset and internal references."""

import argparse
import json
import sys

from inventory import analyze
from template_io import DIST, TemplateError, read_xml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", default=DIST)
    args = parser.parse_args()
    try:
        report = analyze(read_xml(args.xml))
        print(json.dumps({
            "structure": "project subset",
            "counts": report["counts"],
            "uuid_count": len(report["entities"]),
            "errors": report["errors"],
            "macro_scope_warnings": len(report["warnings"]),
        }, ensure_ascii=False, indent=2))
        return 1 if report["errors"] else 0
    except (TemplateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
