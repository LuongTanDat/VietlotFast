"""Write large immutable tracking portfolios as a streamed, compressed XLSX."""
from __future__ import annotations

import math
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
METHODS = [('web', 'Pipeline web'), ('random', 'Ngẫu nhiên'), ('bayesian', 'Bayesian'), ('ewma', 'EWMA')]
HEADERS = ['Vé', 'Bộ số dự đoán', 'ĐB dự đoán', 'Số chính trùng', 'SL số chính trùng',
           'Trùng ĐB / bóng thứ 7', 'Kết quả', 'Giải trúng', 'Mã giải', 'Ghi chú']
STATUS = {'won': 'Trúng giải', 'lost': 'Không trúng', 'pending': 'Chờ kết quả',
          'unknown': 'Chưa xác định', 'invalid': 'Không hợp lệ', 'unsupported': 'Chưa hỗ trợ'}


def xml_text(value):
    return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value)))


def balls(values):
    return ' '.join(f'{value:02d}' for value in values or [])


def special(value):
    return f'{value:02d}' if type(value) is int else ''


def local_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(
        timezone(timedelta(hours=7))).strftime('%d/%m/%Y %H:%M:%S') if value else ''


def row_xml(index, values):
    cells = []
    for col, value in enumerate(values):
        ref = f'{chr(65 + col)}{index}'
        if type(value) in (int, float) and math.isfinite(value):
            cells.append(f'<c r="{ref}" s="1"><v>{value}</v></c>')
        else:
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{xml_text(value if value is not None else "")}</t></is></c>')
    return f'<row r="{index}">{"".join(cells)}</row>'


def write_sheet(archive, index, headers, rows, count, widths):
    if count + 1 > 1048576:
        raise ValueError('Số hàng vượt giới hạn một sheet Excel.')
    end = f'{chr(64 + len(headers))}{count + 1}'
    with archive.open(f'xl/worksheets/sheet{index}.xml', 'w', force_zip64=True) as stream:
        def put(value):
            stream.write(value.encode('utf-8'))
        put(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS}"><dimension ref="A1:{end}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>')
        put(''.join(f'<col min="{n}" max="{n}" width="{width}" customWidth="1"/>' for n, width in enumerate(widths, 1)))
        put('</cols><sheetData>' + row_xml(1, headers))
        batch, written = [], 0
        for written, row in enumerate(rows, 1):
            batch.append(row_xml(written + 1, row))
            if len(batch) == 500:
                put(''.join(batch))
                batch.clear()
        if written != count:
            raise ValueError('Dữ liệu Excel thiếu vé; không xuất file dở.')
        put(''.join(batch))
        put(f'</sheetData><autoFilter ref="A1:{end}"/></worksheet>')


def write_cycle_xlsx(game, cycle_id, destination, db_path=None, level=10):
    from ai import prediction_effectiveness as pe
    # One DB snapshot, recorded actual only; no model, canonical or rescoring.
    data = pe.export_cycle(game, cycle_id, db_path, level, allow_large=True)
    destination = Path(destination)
    overview = [['Loại vé', game], ['Kỳ', str(data['targetDrawId'])],
                *([['Bậc Keno', level]] if game == 'KENO' else []),
                ['Trạng thái', 'Đã chấm' if data['status'] == 'scored' else 'Chờ kết quả'],
                ['Bộ số thực tế', balls(data['actualMain'])], ['ĐB / bóng thứ 7 thực tế', special(data['actualSpecial'])],
                ['Dữ liệu đến kỳ', str(data['cutoffDrawId'])], ['Đã khóa lúc (giờ Việt Nam)', local_time(data['createdAt'])],
                ['Hạn khóa (giờ Việt Nam)', local_time(data['deadline'])], ['Mã kỳ dự đoán', data['cycleId']],
                ['Checksum dữ liệu', data['dataHash']], ['Nguồn kết quả', data['actualSource']],
                ['Phạm vi', 'Toàn bộ vé đã khóa của bốn phương pháp trong kỳ được chọn.']]
    for key, label in METHODS:
        entry = data['methods'][key]
        if entry.get('ticketClass') == 'bao':
            overview.extend([[f'{label} · Số tổ hợp quy đổi', entry['equivalentTicketCount']]])
        overview.extend([[f'{label} · Số Bao' if entry.get('ticketClass') == 'bao' else f'{label} · Số vé', entry['ticketCount']],
                         [f'{label} · Số Bao trúng' if entry.get('ticketClass') == 'bao' else f'{label} · Số vé trúng', entry.get('winningBaoCount', entry['prizeStatistics']['winningTicketCount'])],
                         [f'{label} · Mã dự đoán', entry['predictionId']], [f'{label} · Engine', entry['engine']],
                         [f'{label} · Model', entry['modelId']], [f'{label} · Seed', str(entry['seed'])],
                         [f'{label} · Checksum dự đoán', entry['payloadChecksum']]])
    names = ['Tổng quan'] + [label for _, label in METHODS]
    actual = set(data['actualMain'])
    # Exclusive creation protects a file that happens to share the output name.
    with destination.open('xb') as file:
        try:
            with zipfile.ZipFile(file, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
                archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, 6)) + '</Types>')
                archive.writestr('_rels/.rels', f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
                archive.writestr('xl/workbook.xml', f'<?xml version="1.0"?><workbook xmlns="{NS}" xmlns:r="{REL}"><sheets>' + ''.join(f'<sheet name="{xml_text(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, 1)) + '</sheets></workbook>')
                archive.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, 6)) + f'<Relationship Id="rId6" Type="{REL}/styles" Target="styles.xml"/></Relationships>')
                archive.writestr('xl/styles.xml', f'<?xml version="1.0"?><styleSheet xmlns="{NS}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
                write_sheet(archive, 1, ['Thông tin', 'Giá trị'], overview, len(overview), [40, 88])
                for sheet, (key, _) in enumerate(METHODS, 2):
                    entry = data['methods'].pop(key)
                    if entry.get('ticketClass') == 'bao':
                        headers = ['Bao', 'Bộ số Bao gốc', 'Số đặc biệt', 'Số tổ hợp quy đổi', 'Số chính trùng', 'SL số chính trùng', 'Kết quả', 'Chi tiết giải']
                        def rows():
                            for parent in entry['baoParents']:
                                yield [parent['parentIndex'], balls(parent['main']), special(parent.get('special')), parent['childCount'],
                                       balls([n for n in parent['main'] if n in actual]), len(set(parent['main']) & actual) if actual else '',
                                       parent['result']['label'], parent['result']['details']]
                        write_sheet(archive, sheet, headers, rows(), entry['ticketCount'], [9, 55, 15, 22, 30, 22, 25, 70])
                        del entry
                        continue
                    def rows():
                        for index, (ticket, result) in enumerate(zip(entry['tickets'], entry['ticketResults']), 1):
                            yield [index, balls(ticket['main']), special(ticket.get('special')),
                                   balls([n for n in ticket['main'] if n in actual]),
                                   result['mainHits'] if result['mainHits'] is not None else '',
                                   'Có' if result['specialMatched'] is True else 'Không' if result['specialMatched'] is False else '',
                                   STATUS.get(result['status'], result['status']), result['prizeLabel'], result['prizeCode'], result['reason']]
                    write_sheet(archive, sheet, HEADERS, rows(), entry['ticketCount'], [9, 34, 15, 30, 22, 27, 20, 25, 25, 55])
                    del entry
        except BaseException:
            file.close()
            destination.unlink(missing_ok=True)
            raise
    return {'ok': True, 'type': game, 'cycleId': cycle_id, 'targetDrawId': data['targetDrawId'],
            'bytes': destination.stat().st_size}
