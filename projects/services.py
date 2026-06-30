import io
import mimetypes

import pypdfium2 as pdfium

from core.ai_provider import AIProviderError, extract_floor_plan

SUPPORTED_IMAGE_MIME_TYPES = ('image/jpeg', 'image/png', 'image/webp')
PDF_RENDER_SCALE = 2.5  # multiplier on the PDF's native 72dpi -> ~180dpi, sharp enough for dimension text


class ExtractionError(Exception):
    pass


def _render_pdf_first_page_to_png(file_path):
    """Floor plan PDFs are vector/text drawings, not photos — the vision model
    needs a raster image, so render just the first page (multi-page floor
    plan PDFs aren't supported; a typical Nigerian floor plan submission is
    one page) to a PNG in memory.

    pypdfium2 wraps a native C library — PdfDocument/PdfPage/PdfBitmap hold
    native memory that Python's GC doesn't reliably reclaim promptly, so each
    is explicitly closed rather than left for __del__ (matters on a
    long-running server handling many uploads, not just this one call)."""
    pdf = page = bitmap = None
    try:
        try:
            pdf = pdfium.PdfDocument(file_path)
            page = pdf[0]
        except (pdfium.PdfiumError, IndexError) as exc:
            raise ExtractionError(
                f'Could not read this PDF ({exc}). It may be corrupted, password-protected, or empty - '
                'add rooms manually below.'
            ) from exc

        bitmap = page.render(scale=PDF_RENDER_SCALE)
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if pdf is not None:
            pdf.close()


def extract_rooms_from_floor_plan(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)

    if mime_type == 'application/pdf':
        image_bytes = _render_pdf_first_page_to_png(file_path)
        mime_type = 'image/png'
    elif mime_type in SUPPORTED_IMAGE_MIME_TYPES:
        with open(file_path, 'rb') as f:
            image_bytes = f.read()
    else:
        raise ExtractionError(
            'Automatic extraction currently supports PDF, JPG, PNG, or WEBP floor plan files - '
            'add rooms manually below.'
        )

    try:
        return extract_floor_plan(image_bytes, mime_type)
    except AIProviderError as exc:
        raise ExtractionError(str(exc)) from exc
