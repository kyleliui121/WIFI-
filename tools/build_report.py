"""Generate the extension report from the current four-AC and cross-check CSVs."""
from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Inches

from tools.analyze_ext34 import build_summary
from tools.compare_ns3 import compare, plot, write


def write_docx(markdown: str, folder: Path, output: Path, with_ns3: bool) -> None:
    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                if any(cell.strip("-: ") for cell in cells):
                    rows.append(cells)
                index += 1
            table = doc.add_table(rows=1, cols=len(rows[0]))
            table.style = "Table Grid"
            for cell, value in zip(table.rows[0].cells, rows[0]):
                cell.text = value
            for row in rows[1:]:
                for cell, value in zip(table.add_row().cells, row):
                    cell.text = value
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:], 0)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 1)
        elif line:
            doc.add_paragraph(line)
        index += 1

    doc.add_heading("实验图表", 1)
    for number in range(11, 17 if with_ns3 else 15):
        for image in sorted(folder.glob(f"{number:02}_ext*.png")):
            doc.add_picture(str(image), width=Inches(8.2))
    doc.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results/ext34"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--ns3-csv", type=Path)
    args = parser.parse_args()
    local_ns3 = args.results / "ns3_crosscheck.csv"
    ns3 = args.ns3_csv or (local_ns3 if local_ns3.is_file() else None)
    output = args.out or args.results / "report"
    try:
        rows = None
        if ns3 is not None:
            rows, totals = compare(args.results / "ns3_simpy_crosscheck.csv", ns3)
            write(args.results / "ext_ns3_comparison.csv", rows)
            write(args.results / "ext_ns3_totals.csv", totals)
            plot(args.results, rows)
        markdown = build_summary(args.results, rows)
        output.mkdir(parents=True, exist_ok=True)
        (args.results / "ext4ac_tables.md").write_text(markdown, encoding="utf-8")
        (output / "拓展34-说明.md").write_text(markdown, encoding="utf-8")
        write_docx(markdown, args.results, output / "拓展34-说明.docx", ns3 is not None)
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f"Could not build extension report: {exc}\n")
    print(f"Markdown and Word reports written to {output}")


if __name__ == "__main__":
    main()
