"""
Leitor de ficheiros Excel via XML direto.
Os ficheiros da Atrian tem estilos XML invalidos que fazem o openpyxl falhar,
por isso lemos o ZIP/XML diretamente.
"""
import zipfile
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta
from .models import PickingLine


NS = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def _read_xlsx_sheet(zip_file, sheet_path, shared_strings):
    """Le uma folha de Excel e devolve lista de dicionarios {celula: valor}."""
    try:
        sheet_xml = zip_file.read(sheet_path)
    except KeyError:
        return []

    root = ET.fromstring(sheet_xml)
    rows_data = []

    for row_el in root.findall('.//ns:row', NS):
        row = {}
        for cell in row_el.findall('ns:c', NS):
            ref = cell.get('r')
            col = re.match(r'([A-Z]+)', ref).group(1)
            cell_type = cell.get('t')
            val_el = cell.find('ns:v', NS)
            if val_el is None or val_el.text is None:
                continue
            val = val_el.text
            if cell_type == 's':
                idx = int(val)
                val = shared_strings[idx] if idx < len(shared_strings) else ''
            row[col] = val
        if row:
            rows_data.append(row)
    return rows_data


def _open_xlsx(path):
    """Abre um xlsx e devolve (zipfile, shared_strings, sheet_map)."""
    zf = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in zf.namelist():
        ss_root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
        for si in ss_root.findall('.//ns:si', NS):
            parts = []
            for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                if t.text:
                    parts.append(t.text)
            shared.append(''.join(parts))

    wb_root = ET.fromstring(zf.read('xl/workbook.xml'))
    sheets = [(s.get('name'),
               s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'))
              for s in wb_root.findall('.//ns:sheet', NS)]

    rels_root = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
    rid_map = {r.get('Id'): r.get('Target') for r in rels_root}

    sheet_map = {}
    for name, rid in sheets:
        target = rid_map.get(rid, '')
        path_in_zip = f"xl/{target}" if not target.startswith('/') else target[1:]
        if path_in_zip not in zf.namelist():
            path_in_zip = f"xl/worksheets/{target}"
        sheet_map[name] = path_in_zip

    return zf, shared, sheet_map


def _safe_float(val, default=0.0):
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _serial_to_date(serial):
    """Converte serial date do Excel para datetime."""
    try:
        serial = int(float(serial))
        return datetime(1899, 12, 30) + timedelta(days=serial)
    except (ValueError, TypeError):
        return None


def load_picking_map(path):
    """
    Le o Input 1 (Mapa de Picking).
    Devolve: (lista de PickingLine, expedition_date como datetime)
    """
    zf, shared, sheet_map = _open_xlsx(path)

    sheet_name = list(sheet_map.keys())[0]
    rows = _read_xlsx_sheet(zf, sheet_map[sheet_name], shared)
    zf.close()

    if not rows:
        raise ValueError(f"Ficheiro vazio: {path}")

    header = rows[0]
    data_rows = rows[1:]

    lines = []
    exp_date = None

    for i, row in enumerate(data_rows):
        date_val = row.get('G', '')
        if exp_date is None and date_val:
            exp_date = _serial_to_date(date_val)

        line = PickingLine(
            row_index=i,
            client_code=row.get('A', ''),
            client_name=row.get('B', ''),
            article_code=row.get('C', ''),
            article_desc=row.get('D', ''),
            quantity=_safe_int(row.get('E', '0')),
            transporter=row.get('F', ''),
            expedition_date=row.get('G', ''),
            doc_final=row.get('H', ''),
            doc_origin=row.get('I', ''),
            delegation=row.get('J', ''),
            weight=_safe_float(row.get('K', '0')),
            address1=row.get('L', ''),
            address2=row.get('M', ''),
            address3=row.get('N', ''),
            postal_code=row.get('O', ''),
            city=row.get('P', ''),
            obs_external=row.get('Q', ''),
            shipping_address=row.get('R', ''),
            lot=row.get('S', ''),
            sale_unit=row.get('T', ''),
            expedition_address=row.get('U', ''),
            height=_safe_float(row.get('V', '0')),
            width=_safe_float(row.get('W', '0')),
            depth=_safe_float(row.get('X', '0')),
            route_code=row.get('Y', ''),
        )
        lines.append(line)

    return lines, exp_date


def load_criteria(path):
    """
    Le o Input 2 (Criterios, Mapa de Distribuicao, Matriculas).
    Devolve dicionario com as folhas relevantes.
    Por agora retornamos os dados crus — os parametros ja estao no config.yaml.
    """
    zf, shared, sheet_map = _open_xlsx(path)

    result = {}
    for name, spath in sheet_map.items():
        result[name] = _read_xlsx_sheet(zf, spath, shared)

    zf.close()
    return result
