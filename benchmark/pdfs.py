"""Fixture PDFs for the test vault. Facts live on known pages so paging can be scored."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

_PAPERS = "Papers"

PAGES = {
    "clip-objective.pdf": [
        "Clip Objective Bench CLIP-BENCH-TOKEN",
        "page 2 filler about clipping",
        "page 3 filler about advantage",
        "page 4 filler about ratio",
        "BENCH-EPSILON 0.17",
        "page 6 filler conclusion",
    ],
    "gumbel-search.pdf": [
        "Gumbel Search Bench GUMBEL-BENCH-SEED 42",
        "page 2 filler about simulations",
    ],
}


def write_fixture_pdfs(vault: Path) -> None:
    directory = Path(vault) / _PAPERS
    directory.mkdir(parents=True, exist_ok=True)
    for name, pages in PAGES.items():
        _write_pdf(directory / name, pages)


def _write_pdf(path: Path, pages: list[str]) -> None:
    writer = PdfWriter()
    for text in pages:
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[-1]
        stream = DecodedStreamObject()
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode())
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = stream
    with path.open("wb") as handle:
        writer.write(handle)
