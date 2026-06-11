"""
Gerador de guias PDF individuais para cada motorista.
Cada PDF contem: dados do motorista, resumo da rota, lista de paragens
com horarios previstos e janelas de entrega.
"""
import io
import zipfile
from fpdf import FPDF


class DriverGuidePDF(FPDF):
    """PDF com header e footer personalizados."""

    def __init__(self, driver_name, plate, date_str):
        super().__init__()
        self.driver_name = driver_name
        self.plate = plate
        self.date_str = date_str

    def header(self):
        self.set_font('Helvetica', 'B', 14)
        self.cell(0, 8, 'GUIA DO MOTORISTA', align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_font('Helvetica', '', 10)
        self.cell(0, 6, f'{self.driver_name}  |  {self.plate}  |  {self.date_str}',
                  align='C', new_x='LMARGIN', new_y='NEXT')
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Atrian Norte - Roteador  |  Pagina {self.page_no()}',
                  align='C')


def _safe(text):
    """Remove caracteres que podem causar problemas no PDF."""
    if not text:
        return ""
    return str(text).encode('latin-1', errors='replace').decode('latin-1')


def generate_driver_guide(plan, expedition_date, config):
    """
    Gera PDF com o guia de rota para um motorista.

    Args:
        plan: RoutePlan com a rota do motorista
        expedition_date: datetime da data de expedicao
        config: configuracao

    Returns:
        bytes: conteudo do PDF
    """
    DAY_NAMES = {0: 'Segunda', 1: 'Terca', 2: 'Quarta', 3: 'Quinta',
                 4: 'Sexta', 5: 'Sabado', 6: 'Domingo'}
    weekday = expedition_date.weekday()
    day_name = DAY_NAMES.get(weekday, '')
    date_str = expedition_date.strftime('%d/%m/%Y')

    pdf = DriverGuidePDF(
        _safe(plan.vehicle.driver),
        plan.vehicle.plate,
        f"{date_str} ({day_name})"
    )
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Resumo da rota ──
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, 'RESUMO DA ROTA', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)

    pdf.set_font('Helvetica', '', 10)
    info = [
        ('Motorista', _safe(plan.vehicle.driver)),
        ('Matricula', plan.vehicle.plate),
        ('Data', f"{date_str} ({day_name})"),
        ('Zonas', _safe(', '.join(plan.zones))),
        ('Total clientes', str(plan.total_clients)),
        ('Total caixas', str(plan.total_boxes)),
        ('Km estimados', f"{plan.total_km:.0f} km"),
        ('Horas estimadas', f"{plan.total_hours:.1f}h"),
        ('Saida armazem', plan.departure_time),
        ('Ultimo cliente', plan.last_client_departure),
        ('Chegada a casa', plan.arrival_home),
    ]

    for label, value in info:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(45, 6, f'{label}:', new_x='RIGHT')
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 6, value, new_x='LMARGIN', new_y='NEXT')

    if plan.tiago_supports:
        support_name = (config.get('support_driver') or {}).get(
            'display_name', 'Viatura de apoio')
        red_pct = int(config.get('support_driver_reduction',
                                  config.get('tiago_support_reduction', 0.10)) * 100)
        pdf.ln(2)
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 6, f'* {support_name} apoia nesta rota (-{red_pct}% tempo descarga)',
                 new_x='LMARGIN', new_y='NEXT')

    pdf.ln(6)

    # ── Tabela de paragens ──
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, 'PARAGENS', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)

    # Header da tabela
    col_widths = [12, 60, 35, 18, 20, 45]  # Ordem, Cliente, Cidade, Cx, Hora, Janela
    headers = ['#', 'Cliente', 'Cidade', 'Cx', 'Hora', 'Janela/Obs']

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(52, 73, 94)
    pdf.set_text_color(255, 255, 255)
    for i, (w, h) in enumerate(zip(col_widths, headers)):
        pdf.cell(w, 7, h, border=1, fill=True, align='C',
                 new_x='RIGHT' if i < len(headers) - 1 else 'LMARGIN',
                 new_y='TOP' if i < len(headers) - 1 else 'NEXT')

    # Linhas da tabela
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Helvetica', '', 9)

    for a in plan.stops:
        # Verificar se precisa nova pagina
        if pdf.get_y() > 260:
            pdf.add_page()
            # Re-imprimir header da tabela
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_fill_color(52, 73, 94)
            pdf.set_text_color(255, 255, 255)
            for i, (w, h) in enumerate(zip(col_widths, headers)):
                pdf.cell(w, 7, h, border=1, fill=True, align='C',
                         new_x='RIGHT' if i < len(headers) - 1 else 'LMARGIN',
                         new_y='TOP' if i < len(headers) - 1 else 'NEXT')
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Helvetica', '', 9)

        # Cor alternada
        row_idx = a.delivery_order
        if row_idx % 2 == 0:
            pdf.set_fill_color(240, 240, 240)
            fill = True
        else:
            fill = False

        # Construir texto de janela/obs
        janela = _safe(a.stop.time_window_text) if a.stop.time_window_text else ""
        if a.stop.time_window_end:
            if a.arrival_minutes <= a.stop.time_window_end:
                janela = f"OK {janela}"
            else:
                janela = f"ATRASO {janela}"

        # Verificar se ha obs externas relevantes
        obs_parts = []
        for line in a.stop.lines:
            if line.obs_external and str(line.obs_external).strip() not in ('0', ''):
                obs_text = str(line.obs_external).strip()[:40]
                if obs_text not in obs_parts:
                    obs_parts.append(obs_text)
        if obs_parts and not janela:
            janela = _safe('; '.join(obs_parts)[:40])
        elif obs_parts and janela:
            janela = f"{janela}"

        client_name = _safe(a.stop.client_name[:28])
        city = _safe(a.stop.city[:16]) if a.stop.city else ""

        pdf.cell(col_widths[0], 6, str(a.delivery_order), border=1, fill=fill,
                 align='C', new_x='RIGHT')
        pdf.cell(col_widths[1], 6, client_name, border=1, fill=fill,
                 new_x='RIGHT')
        pdf.cell(col_widths[2], 6, city, border=1, fill=fill,
                 new_x='RIGHT')
        pdf.cell(col_widths[3], 6, str(a.stop.total_boxes), border=1, fill=fill,
                 align='C', new_x='RIGHT')
        pdf.cell(col_widths[4], 6, a.estimated_arrival, border=1, fill=fill,
                 align='C', new_x='RIGHT')
        pdf.cell(col_widths[5], 6, janela[:22], border=1, fill=fill,
                 new_x='LMARGIN', new_y='NEXT')

    # ── Notas finais ──
    pdf.ln(8)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.cell(0, 5, 'Os horarios sao estimativas. Adaptar conforme condicoes reais.',
             new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 5, 'Em caso de atraso significativo, contactar o armazem.',
             new_x='LMARGIN', new_y='NEXT')

    # ── Pagina final: mapa da rota ──
    try:
        from .map_generator import generate_route_image
        map_bytes = generate_route_image(plan, config)
        if map_bytes:
            pdf.add_page()
            pdf.set_font('Helvetica', 'B', 14)
            pdf.cell(0, 8, 'MAPA DA ROTA', align='C', new_x='LMARGIN', new_y='NEXT')
            pdf.set_font('Helvetica', '', 10)
            pdf.cell(0, 6,
                     f'{_safe(plan.vehicle.driver)}  |  {plan.vehicle.plate}  |  '
                     f'{plan.total_clients} clientes  |  {plan.total_km:.0f} km',
                     align='C', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(4)
            map_io = io.BytesIO(map_bytes)
            pdf.image(map_io, x=5, w=200)
    except Exception:
        pass  # Se falhar, terminar sem pagina de mapa

    return pdf.output()


def generate_all_guides_zip(route_plans, expedition_date, config):
    """
    Gera um ZIP com todos os guias PDF dos motoristas.

    Returns:
        bytes: conteudo do ficheiro ZIP
    """
    zip_buffer = io.BytesIO()
    date_str = expedition_date.strftime('%Y-%m-%d')

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for plan in route_plans:
            if plan.total_clients == 0:
                continue
            pdf_bytes = generate_driver_guide(plan, expedition_date, config)
            filename = f"GUIA_{plan.vehicle.driver.replace(' ', '_')}_{date_str}.pdf"
            zf.writestr(filename, pdf_bytes)

    return zip_buffer.getvalue()
