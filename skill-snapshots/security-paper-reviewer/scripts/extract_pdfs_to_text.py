#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from extract_pdf_text import extract_pdf_text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract best-effort text from PDFs into .txt files (no external deps)."
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Directory to scan for PDFs (default: current directory).",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Directory to write .txt files (default: next to each PDF).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan PDFs recursively.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .txt outputs.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Limit pages extracted per PDF (0 = all).",
    )
    args = parser.parse_args()

    root = Path(args.dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Directory not found: {root}")

    out_root = Path(args.out_dir).expanduser().resolve() if args.out_dir else None
    if out_root is not None:
        out_root.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(root.rglob("*.pdf") if args.recursive else root.glob("*.pdf"))
    if not pdf_paths:
        print("No PDFs found.")
        return 0

    extracted = 0
    skipped = 0
    failed = 0

    for pdf_path in pdf_paths:
        if out_root is None:
            out_path = pdf_path.with_suffix(".txt")
        else:
            rel = pdf_path.relative_to(root)
            out_path = (out_root / rel).with_suffix(".txt")
            out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        try:
            pages = extract_pdf_text(str(pdf_path))
            if args.max_pages > 0:
                pages = pages[: args.max_pages]

            rendered = []
            for idx, text in enumerate(pages, start=1):
                rendered.append(f"===== Page {idx} =====\n{text}".strip())
            out_path.write_text("\n\n".join(rendered).strip() + "\n", encoding="utf-8")
            extracted += 1
        except Exception as exc:
            failed += 1
            print(f"[ERROR] Failed on {pdf_path}: {exc}")

    print(f"Done. Extracted: {extracted}, skipped: {skipped}, failed: {failed}.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

