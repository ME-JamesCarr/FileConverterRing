"""Document conversions.

Pandoc handles the text formats, Qt WebEngine renders PDF output from HTML,
and PDF input is read with PyMuPDF (text) or pdf2docx (layout) first.
The libraries are imported inside the functions that use them, so the tray
app (which only reads SOURCES/TARGETS) never loads them.
"""
import html
import re
import tempfile
from pathlib import Path

from formats import ext_of, stem_of

CATEGORY = "Document"
SOURCES = {"txt", "md", "html", "docx", "odt", "rtf", "epub", "pdf"}
TARGETS = {"txt", "md", "html", "docx", "odt", "rtf", "epub", "pdf"}

PANDOC_READ = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt",
               "rtf": "rtf", "epub": "epub"}
PANDOC_WRITE = {"txt": "plain", "md": "gfm", "html": "html", "docx": "docx",
                "odt": "odt", "rtf": "rtf", "epub": "epub3"}
CSS = Path(__file__).with_name("document.css")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _txt_to_html(src: Path) -> str:
    """Plain text as HTML: blank lines separate paragraphs, line breaks are kept."""
    text = _read_text(src).replace("\r\n", "\n")
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    body = "\n".join("<p>" + html.escape(p).replace("\n", "<br>\n") + "</p>" for p in paras)
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(stem_of(src))}</title>"
            f"<style>{CSS.read_text()}</style></head><body>{body}</body></html>")


def _pandoc(src: Path, src_ext: str, target: str, dst: Path, media_dir: Path) -> None:
    """Convert src to dst with Pandoc. Images go to media_dir (or are embedded)."""
    import pypandoc

    to = PANDOC_WRITE[target]
    args = [f"--resource-path={src.parent}"]
    if target not in ("txt", "md"):
        args.append("--standalone")   # in Markdown/text this only adds a metadata header
    if src_ext in ("docx", "odt", "epub"):
        args.append(f"--extract-media={media_dir}")
    if target == "html":
        args += [f"--metadata=pagetitle:{stem_of(src)}", "--embed-resources", f"--css={CSS}"]
    elif target == "epub":
        args.append(f"--metadata=title:{stem_of(src)}")
    if src_ext == "txt":
        pypandoc.convert_text(_txt_to_html(src), to, format="html",
                              outputfile=str(dst), extra_args=args)
    else:
        pypandoc.convert_file(str(src), to, format=PANDOC_READ[src_ext],
                              outputfile=str(dst), extra_args=args)


def _to_pdf(src: Path, src_ext: str, dst: Path, tmp: Path) -> None:
    from . import pdf_render

    if src_ext == "html":
        page = src   # render as-is so its own styling and relative images work
    else:
        page = tmp / "page.html"
        if src_ext == "txt":
            page.write_text(_txt_to_html(src), encoding="utf-8")
        else:
            _pandoc(src, src_ext, "html", page, tmp / "media")
    pdf_render.html_to_pdf(page, dst)


def _from_pdf(src: Path, target: str, dst: Path, tmp: Path) -> None:
    import pymupdf
    import pymupdf4llm
    from pdf2docx import Converter as PdfToDocx

    if target == "txt":
        with pymupdf.open(src) as doc:
            text = "\n\n".join(page.get_text() for page in doc)
        dst.write_text(text, encoding="utf-8")
    elif target == "docx":
        # pdf2docx keeps the page layout (columns, positions) as closely as it can.
        conv = PdfToDocx(str(src))
        try:
            conv.convert(str(dst))
        finally:
            conv.close()
    else:
        # Everything else goes via Markdown, which keeps headings, lists and tables.
        md = pymupdf4llm.to_markdown(str(src))
        if target == "md":
            dst.write_text(md, encoding="utf-8")
        else:
            page = tmp / f"{stem_of(src)}.md"
            page.write_text(md, encoding="utf-8")
            _pandoc(page, "md", target, dst, tmp / "media")


def _media_dir(dst: Path, target: str, tmp: Path) -> Path:
    # Markdown links to its images, so they need to live next to it;
    # every other format embeds them, so a temp folder is fine.
    return dst.with_name(f"{dst.stem}_media") if target == "md" else tmp / "media"


def convert(src: Path, dst: Path) -> None:
    src_ext, target = ext_of(src), ext_of(dst)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        if src_ext == "pdf":
            _from_pdf(src, target, dst, tmp)
        elif target == "pdf":
            _to_pdf(src, src_ext, dst, tmp)
        else:
            _pandoc(src, src_ext, target, dst, _media_dir(dst, target, tmp))
