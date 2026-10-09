# -*- coding: utf-8 -*-
"""表格导出工具（仅用标准库，不引入第三方依赖）。

- `write_xlsx(rows, sheet_name)`：生成最小可用的 .xlsx（inlineStr + 数字），Excel/WPS 可直接打开；
- `write_csv(rows)`：UTF-8 BOM + CRLF，Excel 双击不乱码。

用途：批次 3 查询报表的「导出 XLSX / CSV」（需求 D-29：导出 XLSX + CSV，不做 PDF）。
"""
import io
import re
import zipfile

_XML_ESC = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&apos;"))


def _esc(value):
    text = "" if value is None else str(value)
    for a, b in _XML_ESC:
        text = text.replace(a, b)
    # 去掉 XML 1.0 不允许的控制字符（导出脏数据时不至于破坏文件）
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def _col_ref(idx):
    """0 → A，25 → Z，26 → AA。"""
    ref = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        ref = chr(65 + rem) + ref
    return ref


def cell_xml(ref, value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return '<c r="%s" t="b"><v>%d</v></c>' % (ref, 1 if value else 0)
    if isinstance(value, (int, float)):
        return '<c r="%s"><v>%s</v></c>' % (ref, value)
    return '<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, _esc(value))


def write_xlsx(rows, sheet_name="数据"):
    """rows: 二维表（首行视为表头）。返回 .xlsx 的 bytes。

    刻意不带样式（styles.xml）：最小可用、无第三方依赖、不会因样式表写错而打不开；
    表头行不加粗，如需样式请自行扩展 styles.xml 与 s= 属性。
    """
    rows = [list(r) for r in rows]
    if not rows:
        rows = [["（无数据）"]]
    xml_rows = []
    for ri, row in enumerate(rows, start=1):
        cells = "".join(cell_xml("%s%d" % (_col_ref(ci), ri), v) for ci, v in enumerate(row))
        xml_rows.append('<row r="%d">%s</row>' % (ri, cells))
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>%s</sheetData></worksheet>" % "".join(xml_rows)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % _esc(sheet_name)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def write_csv(rows):
    """UTF-8 BOM + CRLF CSV（Excel 直接双击不乱码）。"""
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
