"""Real PDF extraction, OCR, table structure and normalized page provenance."""
from functools import lru_cache
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from ..config import settings


def bbox_normalized(box, width, height):
    x0, y0, x1, y1 = box
    return [max(0, min(1, x0 / width)), max(0, min(1, y0 / height)),
            max(0, min(1, x1 / width)), max(0, min(1, y1 / height))]


def inspect_pdf(path):
    try:
        doc = pdfium.PdfDocument(path)
        count = len(doc)
        doc.close()
    except Exception as exc:
        raise ValueError("PDF rusak atau terenkripsi; unggah PDF yang bisa dibuka tanpa sandi.") from exc
    if not 1 <= count <= settings().max_pages:
        raise ValueError(f"PDF harus berisi 1–{settings().max_pages} halaman.")
    return count


def render_pages(path, directory, progress=None):
    directory.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(path)
    pages = []
    try:
        for index in range(len(doc)):
            page = doc[index]
            width, height = page.get_size()
            # Bound rendering memory for unusually large PDF page dimensions.
            scale = min(1.6, 1800 / max(width, height))
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            image.save(directory / f"{index + 1}.png")
            pages.append({"page_no": index + 1, "width": width, "height": height})
            image.close()
            bitmap.close()
            page.close()
            if progress:
                progress(f"Menyiapkan halaman {index + 1}/{len(doc)}", 0, 0, len(doc), "render")
    finally:
        doc.close()
    return pages


@lru_cache
def rapid_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise ValueError("OCR belum terpasang. Jalankan uv sync --extra ocr.") from exc
    return RapidOCR()


def image_ocr(image_path):
    from PIL import Image
    with Image.open(image_path) as image:
        width, height = image.size
    result = rapid_engine()(str(image_path))
    rows = []
    if result.boxes is not None:
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = [float(point[0]) for point in box], [float(point[1]) for point in box]
            rows.append({"text": str(text), "bbox": bbox_normalized(
                [min(xs), min(ys), max(xs), max(ys)], width, height), "ocr_score": float(score)})
    return rows


def lightweight_parse(path, pages, image_dir, progress=None):
    items, tables, warnings = [], [], []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            found_tables = page.find_tables()
            table_boxes = []
            for index, table in enumerate(found_tables):
                rows = [[str(cell or "") for cell in row] for row in table.extract()]
                if len(rows) < 2:
                    continue
                table_id = f"table-{page_no}-{index}"
                box = bbox_normalized(table.bbox, page.width, page.height)
                tables.append({"id": table_id, "page_no": page_no, "bbox": box, "rows": rows})
                table_boxes.append(table.bbox)
                items.append({"id": table_id, "type": "table", "page_no": page_no,
                              "bbox": box, "text": table_text(rows), "table_id": table_id})
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
            lines = []
            for word in words:
                if any(x0 <= word["x0"] <= x1 and y0 <= word["top"] <= y1
                       for x0, y0, x1, y1 in table_boxes):
                    continue
                if not lines or abs(lines[-1][0]["top"] - word["top"]) > 4:
                    lines.append([])
                lines[-1].append(word)
            for index, line in enumerate(lines):
                box = [min(w["x0"] for w in line), min(w["top"] for w in line),
                       max(w["x1"] for w in line), max(w["bottom"] for w in line)]
                items.append({"id": f"text-{page_no}-{index}", "type": "text", "page_no": page_no,
                              "bbox": bbox_normalized(box, page.width, page.height),
                              "text": " ".join(w["text"] for w in line)})
            if len(" ".join(w["text"] for w in words).strip()) < 20:
                if settings().ocr_enabled:
                    for index, row in enumerate(image_ocr(image_dir / f"{page_no}.png")):
                        items.append({"id": f"ocr-{page_no}-{index}", "type": "text",
                                      "page_no": page_no, **row})
                    warnings.append(f"Halaman {page_no} memakai OCR; periksa angka dan tabel pada sumber.")
                else:
                    warnings.append(f"Halaman {page_no} minim teks. Aktifkan OCR_ENABLED=true untuk scan.")
            if progress:
                progress(f"Membaca teks, tabel & OCR · {page_no}/{len(pages)} halaman",
                         round(page_no / len(pages) * 100), page_no, len(pages), "extract")
    return {"pages": pages, "items": items, "tables": tables, "warnings": warnings,
            "parser": "pdfplumber", "quality": None}


def table_text(rows):
    if not rows:
        return ""
    header = rows[0]
    return "\n".join(" | ".join(f"{header[i] if i < len(header) else i}: {value}"
                               for i, value in enumerate(row)) for row in rows[1:])


@lru_cache
def docling_converter():
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, TesseractCliOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise ValueError("Docling belum terpasang. Jalankan uv sync --extra ai --extra ocr.") from exc
    options = PdfPipelineOptions(do_ocr=settings().ocr_enabled, do_table_structure=True)
    options.ocr_options = (TesseractCliOcrOptions(lang=["ind", "eng"])
                           if settings().ocr_engine == "tesseract" else RapidOcrOptions())
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def docling_page(path, page, converter):
    # Public page_range API preserves the original PDF page number/provenance.
    result = converter.convert(path, page_range=(page["page_no"], page["page_no"]))
    doc = result.document
    items, tables, warnings = [], [], []
    page_map = {page["page_no"]: page}
    for index, (item, _) in enumerate(doc.iterate_items()):
        provenance = getattr(item, "prov", [])
        if not provenance:
            continue
        source = provenance[0]
        page_no = source.page_no
        dimensions = page_map.get(page_no)
        if not dimensions:
            continue
        box = source.bbox.to_top_left_origin(page_height=dimensions["height"])
        normalized = bbox_normalized([box.l, box.t, box.r, box.b], dimensions["width"], dimensions["height"])
        item_id = f"item-{page_no}-{index}"
        if hasattr(item, "export_to_dataframe"):
            frame = item.export_to_dataframe(doc=doc)
            rows = [[str(c) for c in frame.columns]] + frame.fillna("").astype(str).values.tolist()
            tables.append({"id": item_id, "page_no": page_no, "bbox": normalized, "rows": rows})
            items.append({"id": item_id, "type": "table", "page_no": page_no, "bbox": normalized,
                          "table_id": item_id, "text": table_text(rows)})
        elif getattr(item, "text", "").strip():
            items.append({"id": item_id, "type": "text", "page_no": page_no, "bbox": normalized,
                          "text": item.text, "label": str(item.label)})
    quality = None
    if getattr(result, "confidence", None):
        quality = str(result.confidence.mean_grade)
        warnings.append("Grade konversi membantu pemeriksaan OCR; bukan confidence jawaban chatbot.")
    return {"items": items, "tables": tables, "warnings": warnings,
            "parser": "docling", "quality": quality, "docling_document": doc.export_to_dict()}


def docling_parse(path, pages, image_dir, progress=None):
    output = {"pages": pages, "items": [], "tables": [], "warnings": [],
              "parser": "docling", "quality": {}, "docling_pages": []}
    converter = docling_converter()
    for page in pages:
        part = docling_page(path, page, converter)
        for key in ("items", "tables", "warnings"):
            output[key].extend(part[key])
        output["quality"][str(page["page_no"])] = part["quality"]
        output["docling_pages"].append(part["docling_document"])
        if progress:
            done = page["page_no"]
            progress(f"Membaca teks, tabel & OCR · {done}/{len(pages)} halaman",
                     round(done / len(pages) * 100), done, len(pages), "extract")
    output["warnings"] = list(dict.fromkeys(output["warnings"]))
    return output


def parse(path: Path, directory: Path, progress):
    total = inspect_pdf(path)
    progress("Menyiapkan halaman", 0, 0, total, "render")
    pages = render_pages(path, directory, progress)
    progress("Memuat model pembaca, lalu memulai OCR", 0, 0, total, "extract")
    output = (docling_parse if settings().parser_backend == "docling" else lightweight_parse)(
        path, pages, directory, progress)
    if not any(item["text"].strip() for item in output["items"]):
        raise ValueError("Tidak ditemukan teks. Aktifkan OCR atau unggah scan yang lebih jelas.")
    output["items"].sort(key=lambda item: (item["page_no"], item["bbox"][1]))
    return output
