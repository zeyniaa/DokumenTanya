"""Generate synthetic, clearly labeled PDFs. No personal or university data."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak

ROOT = Path(__file__).resolve().parents[1]


def create_example(path):
    styles = getSampleStyleSheet()
    elements = []
    def text(value, style="BodyText"):
        elements.append(Paragraph(value, styles[style]))
        elements.append(Spacer(1, 12))
    text("Panduan Administrasi Akademik", "Title")
    text("DOKUMEN DEMO SINTETIS - bukan kebijakan kampus nyata.")
    text("1. Pengajuan cuti akademik", "Heading2")
    text("Mahasiswa mengajukan cuti melalui formulir CA-01. Persyaratan pengajuan cuti adalah surat permohonan, persetujuan dosen wali, dan bukti bebas tunggakan administrasi.")
    text("Pengajuan diterima paling lambat 14 hari sebelum semester dimulai. Proses verifikasi pengajuan cuti membutuhkan 5 hari kerja setelah dokumen lengkap diterima.")
    text("Cuti dapat diberikan maksimal dua semester berturut-turut. Panduan ini tidak menetapkan batas semester minimum untuk mengajukan cuti.")
    text("2. Biaya layanan administrasi", "Heading2")
    rows = [["Layanan", "Biaya administrasi (Rp)", "Lama proses (hari)"],
            ["Surat aktif kuliah", "25.000", "2"], ["Legalisasi dokumen", "40.000", "3"],
            ["Surat rekomendasi", "15.000", "4"]]
    table = Table(rows, colWidths=[170, 160, 140], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e7efdf")),
        ("GRID", (0,0), (-1,-1), .5, colors.HexColor("#7a8b72")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 9),
        ("TOPPADDING", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 10)]))
    elements.append(table)
    elements.extend([Spacer(1, 15), PageBreak()])
    text("3. Pengembalian biaya", "Heading2")
    text("Biaya dapat dikembalikan jika layanan belum diproses. Pemohon melampirkan nomor permohonan dan bukti pembayaran. Pengembalian diselesaikan dalam 7 hari kerja setelah permohonan disetujui.")
    text("4. Kontak layanan", "Heading2")
    text("Layanan administrasi buka Senin sampai Jumat, pukul 08.00-16.00. Pertanyaan disampaikan melalui loket administrasi. Dokumen ini tidak mencantumkan nomor telepon atau alamat email.")
    text("5. Catatan penggunaan", "Heading2")
    text("Semua nama layanan, biaya, waktu, dan persyaratan pada dokumen ini dibuat khusus untuk demonstrasi dan pengujian aplikasi DokumenTanya.")
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=50, leftMargin=50).build(elements)


if __name__ == "__main__":
    create_example(ROOT / "examples/sop-demo.pdf")
    # Rasterize page 1, then put it in a PDF to test OCR instead of native extraction.
    import pypdfium2 as pdfium
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    pdf = pdfium.PdfDocument(ROOT / "examples/sop-demo.pdf")
    page = pdf[0]
    bitmap = page.render(scale=2)
    image = bitmap.to_pil()
    c = canvas.Canvas(str(ROOT / "examples/sop-scan-demo.pdf"), pagesize=A4)
    c.drawImage(ImageReader(image), 0, 0, width=A4[0], height=A4[1])
    c.save()
    image.close()
    bitmap.close()
    page.close()
    pdf.close()
    print("Created examples/sop-demo.pdf and examples/sop-scan-demo.pdf")
