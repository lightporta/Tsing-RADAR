"""Font selection must validate embeddability and Chinese glyphs."""

import io

import pytest
from fastapi import HTTPException
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.core.config import settings
from app.services.artifact_generation import _find_cjk_font


def test_detected_cjk_font_can_embed_and_roundtrip_chinese(monkeypatch):
    monkeypatch.setattr(settings, "DOCUMENT_CJK_FONT_PATH", None)
    path = _find_cjk_font()
    kwargs = {"subfontIndex": 0} if path.suffix.lower() == ".ttc" else {}
    pdfmetrics.registerFont(TTFont("CJKRoundtripTest", str(path), **kwargs))
    payload = io.BytesIO()
    canvas = Canvas(payload)
    canvas.setFont("CJKRoundtripTest", 12)
    canvas.drawString(20, 700, "清研寻师 导师匹配 简历")
    canvas.save()
    reader = PdfReader(io.BytesIO(payload.getvalue()))
    assert "清研寻师 导师匹配 简历" in reader.pages[0].extract_text()
    # FontFile2 is an embedded TrueType subset, not a reader-side system fallback.
    fonts = reader.pages[0]["/Resources"]["/Font"].get_object()
    assert any(
        "/FontFile2" in font.get_object().get("/FontDescriptor", {})
        for font in fonts.values()
    )


def test_explicit_invalid_font_does_not_silently_fall_back(tmp_path, monkeypatch):
    invalid = tmp_path / "invalid.ttf"
    invalid.write_bytes(b"not a TrueType font")
    monkeypatch.setattr(settings, "DOCUMENT_CJK_FONT_PATH", str(invalid))
    with pytest.raises(HTTPException) as error:
        _find_cjk_font()
    assert error.value.status_code == 503
    assert "DOCUMENT_CJK_FONT_PATH" in error.value.detail
