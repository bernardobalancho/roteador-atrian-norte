"""
Roteador Atrian Norte — App Web
Uso diário: upload do mapa de picking → roteamento → download dos outputs.
"""
import streamlit as st
import yaml
import os
import tempfile
import io
from datetime import datetime, timedelta

from engine.loader import load_picking_map, load_criteria
from engine.router import route
from engine.writer import write_routed_map, write_pre_carga
from engine.geo import _check_osrm
from engine.pdf_guide import generate_all_guides_zip
from engine.map_generator import generate_route_map


st.set_page_config(
    page_title="Atrian Logistics — Roteador",
    page_icon="🚛",
    layout="wide",
)

# ── Password Gate ──
# st.secrets.get() falha se nao existir .streamlit/secrets.toml — usar try/except
try:
    APP_PASSWORD = st.secrets.get("APP_PASSWORD", "atrian2025")
except Exception:
    APP_PASSWORD = "atrian2025"


def check_password():
    """Ecrã de login simples com password partilhada."""
    if st.session_state.get("authenticated"):
        return True

    st.markdown(
        """
        <div style="display:flex; flex-direction:column; align-items:center;
                    justify-content:center; padding-top:6rem;">
            <div style="width:64px; height:64px; background:#BA0C2F;
                        border-radius:14px; display:flex; align-items:center;
                        justify-content:center; font-family:'Montserrat',sans-serif;
                        font-weight:800; color:white; font-size:1.8rem;
                        box-shadow: 0 8px 32px rgba(186,12,47,0.30);">A</div>
            <h2 style="font-family:'Montserrat',sans-serif; font-weight:700;
                       margin:1.2rem 0 0.2rem 0; color:#E2E2E2;">Atrian Logistics</h2>
            <p style="font-family:'Hanken Grotesk',sans-serif;
                      color:#7A7A7A; text-transform:uppercase;
                      letter-spacing:0.1em; font-size:0.78rem;
                      margin-bottom:1.6rem;">Roteador de Distribuição</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        pwd = st.text_input("Password", type="password", label_visibility="collapsed",
                            placeholder="Password")
        if st.button("Entrar", type="primary", use_container_width=True):
            if pwd == APP_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Password incorreta.")
    return False


# ── CSS (Atrian Professional Distribution design system) ──
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&family=Hanken+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">
<style>
    /* ── Base tokens ── */
    :root {
        --surface-deep: #0A0A0A;
        --surface-elevated: #1E1E1E;
        --surface-container: #1E2020;
        --surface-container-high: #282A2B;
        --on-surface: #E2E2E2;
        --on-surface-muted: #ABABAB;
        --on-surface-dim: #7A7A7A;
        --brand-red: #BA0C2F;
        --brand-red-bright: #E11D48;
        --status-success: #2ECC71;
        --status-warning: #F1C40F;
        --outline: #3E3E3E;
        --outline-soft: rgba(171,136,136,0.12);
    }

    html, body, [class*="css"], .stApp {
        font-family: 'Hanken Grotesk', sans-serif !important;
        background-color: var(--surface-deep) !important;
        color: var(--on-surface);
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em;
        color: var(--on-surface) !important;
    }

    /* ── Topbar / hero ── */
    .atrian-topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.8rem 0 1.4rem 0;
        border-bottom: 1px solid var(--outline-soft);
        margin-bottom: 1.6rem;
    }
    .atrian-brand {
        display: flex; align-items: center; gap: 0.8rem;
    }
    .atrian-brand-mark {
        width: 36px; height: 36px;
        background: var(--brand-red);
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        font-family: 'Montserrat', sans-serif;
        font-weight: 800;
        color: white; font-size: 1.1rem;
    }
    .atrian-brand-name {
        font-family: 'Montserrat', sans-serif;
        font-weight: 700; font-size: 1.05rem;
        color: var(--on-surface);
    }
    .atrian-brand-sub {
        font-family: 'Hanken Grotesk', sans-serif;
        font-size: 0.78rem;
        color: var(--on-surface-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .main-title {
        font-family: 'Montserrat', sans-serif !important;
        font-size: 2rem; font-weight: 700;
        color: var(--on-surface);
        margin: 0.4rem 0 0.2rem 0;
    }
    .sub-title {
        font-family: 'Hanken Grotesk', sans-serif;
        font-size: 1rem;
        color: var(--on-surface-muted);
        margin-bottom: 1.6rem;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: var(--surface-elevated) !important;
        border-right: 1px solid var(--outline-soft);
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 600 !important;
        color: var(--on-surface) !important;
    }
    section[data-testid="stSidebar"] .stMarkdown p {
        color: var(--on-surface-muted);
        font-size: 0.92rem;
    }

    /* Sidebar section labels (subheader chip-style) */
    section[data-testid="stSidebar"] .stHeading h2,
    section[data-testid="stSidebar"] .stHeading h3 {
        text-transform: uppercase;
        font-size: 0.72rem !important;
        letter-spacing: 0.1em;
        color: var(--on-surface-muted) !important;
        font-weight: 600 !important;
        margin-top: 0.4rem;
    }

    /* ── Cards / containers ── */
    div[data-testid="stMetric"] {
        background: var(--surface-elevated);
        border: 1px solid var(--outline-soft);
        border-radius: 12px;
        padding: 1rem 1.2rem;
        transition: border-color 0.15s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: var(--brand-red);
    }
    div[data-testid="stMetric"] label {
        font-family: 'Hanken Grotesk', sans-serif !important;
        text-transform: uppercase;
        font-size: 0.72rem !important;
        letter-spacing: 0.08em;
        color: var(--on-surface-muted) !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
        font-size: 1.7rem !important;
        color: var(--on-surface) !important;
    }

    /* ── Buttons ── */
    .stButton > button,
    .stDownloadButton > button {
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 0.01em;
        border-radius: 8px !important;
        padding: 0.6rem 1.2rem !important;
        border: none !important;
        transition: filter 0.15s ease, transform 0.05s ease;
    }
    .stButton > button[kind="primary"],
    .stDownloadButton > button {
        background: var(--brand-red) !important;
        color: white !important;
        box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset,
                    0 8px 24px rgba(186, 12, 47, 0.25);
    }
    .stButton > button[kind="primary"]:hover,
    .stDownloadButton > button:hover {
        filter: brightness(1.08);
        color: white !important;
    }
    .stButton > button[kind="secondary"] {
        background: transparent !important;
        color: var(--on-surface) !important;
        border: 1px solid var(--outline) !important;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: var(--brand-red) !important;
        color: var(--on-surface) !important;
    }

    /* ── Inputs ── */
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea {
        background: var(--surface-container) !important;
        border: 1px solid var(--outline) !important;
        border-radius: 8px !important;
        color: var(--on-surface) !important;
        font-family: 'Hanken Grotesk', sans-serif !important;
    }
    .stTextInput input:focus,
    .stNumberInput input:focus {
        border-color: var(--brand-red) !important;
        box-shadow: 0 0 0 2px rgba(186,12,47,0.18) !important;
    }
    .stSlider [data-baseweb="slider"] > div > div { background: var(--brand-red) !important; }

    /* Checkbox */
    .stCheckbox label p { color: var(--on-surface) !important; font-family: 'Hanken Grotesk', sans-serif !important; }

    /* ── File uploader cards ── */
    section[data-testid="stFileUploader"] {
        background: var(--surface-elevated);
        border: 1px dashed var(--outline);
        border-radius: 12px;
        padding: 1rem;
        transition: border-color 0.15s ease;
    }
    section[data-testid="stFileUploader"]:hover {
        border-color: var(--brand-red);
    }
    section[data-testid="stFileUploader"] button {
        background: transparent !important;
        border: 1px solid var(--outline) !important;
        color: var(--on-surface) !important;
    }

    /* ── Expanders (vehicle detail rows) ── */
    div[data-testid="stExpander"] {
        background: var(--surface-elevated);
        border: 1px solid var(--outline-soft) !important;
        border-radius: 12px !important;
        margin-bottom: 0.6rem;
    }
    div[data-testid="stExpander"] summary {
        font-family: 'Hanken Grotesk', sans-serif !important;
        color: var(--on-surface) !important;
        padding: 0.4rem 0.6rem;
    }
    div[data-testid="stExpander"]:hover {
        border-color: var(--brand-red) !important;
    }

    /* ── Status / alert callouts ── */
    div[data-testid="stAlert"] {
        background: var(--surface-elevated) !important;
        border: 1px solid var(--outline-soft) !important;
        border-radius: 10px !important;
        color: var(--on-surface) !important;
    }
    div[data-testid="stAlert"][data-baseweb="notification"] svg { color: var(--brand-red); }

    /* Pill-shaped success chip used for the OSRM ok message */
    .atrian-pill {
        display: inline-flex; align-items: center; gap: 0.4rem;
        padding: 0.35rem 0.8rem;
        border-radius: 9999px;
        font-family: 'Hanken Grotesk', sans-serif;
        font-size: 0.82rem; font-weight: 600;
        background: rgba(46, 204, 113, 0.12);
        color: var(--status-success);
        border: 1px solid rgba(46, 204, 113, 0.25);
    }
    .atrian-pill.warn {
        background: rgba(241, 196, 15, 0.10);
        color: var(--status-warning);
        border-color: rgba(241, 196, 15, 0.25);
    }
    .atrian-pill.brand {
        background: rgba(186, 12, 47, 0.12);
        color: #ffb3b3;
        border-color: rgba(186, 12, 47, 0.30);
    }

    /* ── Dataframe / tables ── */
    div[data-testid="stDataFrame"] {
        background: var(--surface-elevated);
        border: 1px solid var(--outline-soft);
        border-radius: 10px;
    }

    /* ── Progress bar ── */
    .stProgress > div > div > div > div {
        background-color: var(--brand-red) !important;
    }

    /* ── Dividers ── */
    hr {
        border-color: var(--outline-soft) !important;
        margin: 1.4rem 0 !important;
    }

    /* Legacy classes (kept for compat) */
    .status-ok { color: var(--status-success); font-weight: 600; }
    .status-warn { color: var(--status-warning); font-weight: 600; }
    .status-error { color: #ff6b6b; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


def load_config(region: str = "Porto"):
    """Carrega config_<regiao>.yaml. Fallback para config.yaml legacy."""
    base = os.path.dirname(__file__)
    candidates = [
        os.path.join(base, f'config_{region.lower()}.yaml'),
        os.path.join(base, 'config.yaml'),       # backward compat
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(f"Nao foi encontrado config para regiao '{region}'")


def available_regions():
    """Devolve a lista de regioes disponiveis (config_X.yaml encontrados)."""
    base = os.path.dirname(__file__)
    regions = []
    for f in os.listdir(base):
        if f.startswith('config_') and f.endswith('.yaml'):
            name = f[len('config_'):-len('.yaml')]
            regions.append(name.capitalize())
    if not regions and os.path.exists(os.path.join(base, 'config.yaml')):
        regions = ['Porto']  # legacy fallback
    return sorted(regions)


def save_uploaded_file(uploaded_file):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    return tmp.name


def format_hours(h):
    hours = int(h)
    mins = int((h - hours) * 60)
    return f"{hours}h{mins:02d}"


def main():
    if not check_password():
        return

    # ── Seletor de regiao (Porto / Lisboa) ──
    regions = available_regions()
    default_region = st.session_state.get('region', regions[0] if regions else 'Porto')
    region = st.sidebar.selectbox(
        "🌍 Região",
        regions,
        index=regions.index(default_region) if default_region in regions else 0,
        key='region_selector',
        help="Cada região tem o seu armazém, frota, zonas e regras."
    )
    if region != st.session_state.get('region'):
        st.session_state['region'] = region
        # Limpa resultados antigos quando muda de regiao
        st.session_state.pop('results', None)

    config = load_config(region)
    region_name = config.get('region', region)

    # ── Topbar (brand) ──
    st.markdown(f"""
    <div class="atrian-topbar">
        <div class="atrian-brand">
            <div class="atrian-brand-mark">A</div>
            <div>
                <div class="atrian-brand-name">Atrian Logistics</div>
                <div class="atrian-brand-sub">Roteador Atrian {region_name}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Header ──
    st.markdown('<p class="main-title">Planeamento de rotas diário</p>', unsafe_allow_html=True)
    sub_map = {
        "Porto": "Zona Norte de Portugal — distribua a sua logística com precisão e agilidade em tempo real.",
        "Lisboa": "Lisboa e Margem Sul — distribua a sua logística com precisão e agilidade em tempo real.",
    }
    st.markdown(
        f'<p class="sub-title">{sub_map.get(region_name, region_name)}</p>',
        unsafe_allow_html=True
    )

    # ── OSRM status ──
    if _check_osrm():
        st.markdown(
            '<span class="atrian-pill">● OSRM ativo — distâncias e tempos reais pela estrada</span>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<span class="atrian-pill warn">● OSRM indisponível — a usar estimativa haversine como fallback</span>',
            unsafe_allow_html=True
        )

    # ── Sidebar: configuração diária ──
    with st.sidebar:
        st.header("📅 Ajustes do dia")
        st.caption(
            "Ajustes **temporários** para o dia (férias, motorista mais lento, etc.). "
            "Para mudanças permanentes (motorista despede-se, nova zona…) "
            "usa a página **⚙️ Configurações**."
        )

        st.subheader("Frota ativa hoje")
        fleet_active = {}
        driver_adjustments = {}
        for v in config['fleet']:
            col_check, col_adj = st.columns([3, 2])
            with col_check:
                fleet_active[v['plate']] = st.checkbox(
                    f"{v['plate']} — {v['driver']}",
                    value=v.get('active', True),
                    key=f"fleet_{v['plate']}"
                )
            with col_adj:
                driver_adjustments[v['plate']] = st.number_input(
                    "Ajuste %",
                    min_value=-30, max_value=30, value=0, step=5,
                    key=f"adj_{v['plate']}",
                    help=f"Ajuste tempo para {v['driver']}. +% = mais tempo (novo motorista), -% = menos tempo (motorista rápido)"
                )

        st.divider()
        st.subheader("Horários")
        start_time = st.text_input("Hora de chegada ao armazém", value=config['work_hours']['normal']['start'])
        max_hours_normal = st.number_input("Máximo horas (dia normal)", value=config['work_hours']['normal']['max_hours'], step=0.5)
        max_hours_reduced = st.number_input("Máximo horas (sáb/seg)", value=config['work_hours']['reduced']['max_hours'], step=0.5)

        st.divider()
        st.subheader("Parâmetros")
        if not _check_osrm():
            road_factor = st.slider("Fator estrada (haversine→real)", 1.1, 1.8, config.get('road_factor', 1.35), 0.05)
        else:
            road_factor = config.get('road_factor', 1.35)
            st.caption("🛰️ Distâncias reais via OSRM")
        st.caption("🚦 Trânsito automático por hora e zona")
        porto_reduction = st.slider(
            "Ajuste centro Porto (%)",
            min_value=-30, max_value=30, value=int(config.get('porto_time_reduction', 0.10) * 100), step=5,
            help="Aplica-se APENAS a entregas na cidade do Porto. Positivo = descarga mais rápida, Negativo = mais tempo (trânsito/estacionar)"
        )

    # Apply sidebar changes to config
    for v in config['fleet']:
        v['active'] = fleet_active.get(v['plate'], True)
        v['driver_adjustment'] = driver_adjustments.get(v['plate'], 0) / 100
    config['work_hours']['normal']['start'] = start_time
    config['work_hours']['reduced']['start'] = start_time
    config['work_hours']['normal']['max_hours'] = max_hours_normal
    config['work_hours']['reduced']['max_hours'] = max_hours_reduced
    config['road_factor'] = road_factor
    config['porto_time_reduction'] = porto_reduction / 100

    # ── Main content: só Input 1 (Mapa de Picking) ──
    # Os critérios, frota, zonas e restrições vivem agora dentro da app
    # (config_*.yaml + página "Configurações")
    st.subheader("📋 Mapa de Picking")
    st.caption(f"Ficheiro Excel com as encomendas do dia para a região **{region_name}**. "
               f"Os critérios e mapa de distribuição vêm da página ⚙️ Configurações.")
    input1_file = st.file_uploader(
        "Upload Input 1",
        type=['xlsx'],
        key='input1',
        label_visibility='collapsed'
    )

    st.divider()

    # ── Botão de roteamento ──
    if input1_file is not None:
        run_button = st.button("🚀 Calcular Rotas", type="primary", use_container_width=True)

        if run_button:
            progress_bar = st.progress(0, text="A ler ficheiro de picking...")
            try:
                input1_path = save_uploaded_file(input1_file)
                input2_path = None  # critérios agora vêm do config interno

                lines, expedition_date = load_picking_map(input1_path)

                if not expedition_date:
                    st.error("Não foi possível extrair a data de expedição do ficheiro.")
                    return

                from engine.geo import _nominatim_cache
                cached_entries = len(_nominatim_cache)
                if cached_entries > 20:
                    progress_bar.progress(10, text=f"📍 A calcular rotas... ({cached_entries} endereços em cache — geocodificação rápida)")
                else:
                    progress_bar.progress(10, text=f"📍 A geocodificar {len(lines)} linhas (1ª execução — pode demorar ~{len(lines)}s — próximas vezes será rápido)")

                route_plans = route(lines, config, expedition_date)
                progress_bar.progress(90, text="A gerar ficheiros de output...")

                date_str = expedition_date.strftime('%Y-%m-%d')
                routed_path = tempfile.mktemp(suffix='.xlsx')
                precarga_path = tempfile.mktemp(suffix='.xlsx')

                write_routed_map(route_plans, lines, config, expedition_date, input2_path, routed_path)
                write_pre_carga(route_plans, lines, config, expedition_date, precarga_path)

                st.session_state['results'] = {
                    'route_plans': route_plans,
                    'lines': lines,
                    'expedition_date': expedition_date,
                    'routed_path': routed_path,
                    'precarga_path': precarga_path,
                    'date_str': date_str,
                    'config': config,
                    'region': region_name.upper(),
                }

                os.unlink(input1_path)
                if input2_path:
                    os.unlink(input2_path)

                progress_bar.progress(100, text="✅ Rotas calculadas!")

            except Exception as e:
                st.error(f"Erro no processamento: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
                return

    # ── Resultados ──
    if 'results' in st.session_state:
        res = st.session_state['results']
        plans = res['route_plans']
        exp_date = res['expedition_date']
        cfg = res['config']

        DAY_NAMES = {0: 'Segunda', 1: 'Terça', 2: 'Quarta', 3: 'Quinta', 4: 'Sexta', 5: 'Sábado', 6: 'Domingo'}
        weekday = exp_date.weekday()
        day_name = DAY_NAMES.get(weekday, '')
        is_reduced = weekday in cfg['work_hours'].get('reduced_days', [])
        max_h = cfg['work_hours']['reduced']['max_hours'] if is_reduced else cfg['work_hours']['normal']['max_hours']

        st.markdown(
            f"<h3 style='font-family:Montserrat,sans-serif; font-weight:600; "
            f"color:var(--on-surface); margin:0.4rem 0;'>"
            f"Expedição: {exp_date.strftime('%d/%m/%Y')} ({day_name})</h3>",
            unsafe_allow_html=True
        )

        # Linha de aviso de dia reduzido + atalhos rápidos para outputs Excel
        warn_col, btn1_col, btn2_col = st.columns([2.5, 1, 1])
        with warn_col:
            if is_reduced:
                st.markdown(
                    f'<span class="atrian-pill brand">● Dia com horário reduzido — máximo {max_h:.0f}h por motorista</span>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<span class="atrian-pill">● Dia normal — máximo {max_h:.0f}h por motorista</span>',
                    unsafe_allow_html=True
                )
        with btn1_col:
            with open(res['routed_path'], 'rb') as f:
                st.download_button(
                    label="Mapa Picking",
                    data=f.read(),
                    file_name=f"MAPA_PICKING_{res.get('region','PORTO')}_{res['date_str']}_ROTEADO.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key='dl_picking_top',
                )
        with btn2_col:
            with open(res['precarga_path'], 'rb') as f:
                st.download_button(
                    label="Mapa Pré-Carga",
                    data=f.read(),
                    file_name=f"MAPA_PRE_CARGA_{res.get('region','PORTO')}_{res['date_str']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key='dl_precarga_top',
                )

        # ── Métricas globais ──
        total_stops = sum(p.total_clients for p in plans)
        total_boxes = sum(p.total_boxes for p in plans)
        total_km = sum(p.total_km for p in plans)
        total_lines = len(res['lines'])
        vehicles_used = len([p for p in plans if p.total_clients > 0])
        violations = sum(
            1 for p in plans for a in p.stops
            if a.stop.time_window_end and a.arrival_minutes > a.stop.time_window_end
        )

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1:
            st.metric("Linhas", f"{total_lines}")
        with m2:
            st.metric("Paragens", f"{total_stops}")
        with m3:
            st.metric("Caixas", f"{total_boxes}")
        with m4:
            st.metric("Viaturas", f"{vehicles_used}")
        with m5:
            st.metric("Km total", f"{total_km:.0f}")
        with m6:
            if violations == 0:
                st.metric("Janelas", "OK", delta="ok", delta_color="normal")
            else:
                st.metric("Janelas", f"{violations}", delta="atraso", delta_color="inverse")

        # ── Listagem de violações de janelas horárias ──
        if violations > 0:
            with st.expander(
                f"⚠️ {violations} janela(s) horária(s) violada(s) — clica para ver detalhes",
                expanded=True
            ):
                violation_rows = []
                for plan in plans:
                    for a in plan.stops:
                        if (a.stop.time_window_end
                                and a.arrival_minutes > a.stop.time_window_end):
                            delay = a.arrival_minutes - a.stop.time_window_end
                            tw_end_h = a.stop.time_window_end // 60
                            tw_end_m = a.stop.time_window_end % 60
                            violation_rows.append({
                                "Motorista": plan.vehicle.driver,
                                "Matrícula": plan.vehicle.plate,
                                "Cliente": a.stop.client_name[:30],
                                "Cidade": a.stop.city,
                                "Janela": a.stop.time_window_text or f"até {tw_end_h:02d}:{tw_end_m:02d}",
                                "Chegada prevista": a.estimated_arrival,
                                "Atraso": f"+{delay} min",
                                "_delay": delay,
                            })
                # Ordenar por atraso descendente
                violation_rows.sort(key=lambda r: -r['_delay'])
                for r in violation_rows:
                    r.pop('_delay', None)
                st.dataframe(violation_rows, use_container_width=True,
                              hide_index=True)
                st.caption(
                    "💡 Dica: se os mesmos clientes aparecem repetidamente, "
                    "ajusta o **mapa de distribuição** ou as **restrições por motorista** "
                    "na página ⚙️ Configurações para evitar atribuições incompatíveis."
                )

        st.divider()

        # ── Detalhe por viatura ──
        st.markdown(
            "<h4 style='font-family:Montserrat,sans-serif; font-weight:600; "
            "color:var(--on-surface); margin:0.8rem 0 0.6rem 0;'>"
            "Detalhe por viatura</h4>",
            unsafe_allow_html=True
        )

        for plan in plans:
            if plan.total_clients == 0:
                continue

            hours_status = "status-ok" if plan.total_hours <= max_h else "status-error"
            hours_icon = "✅" if plan.total_hours <= max_h else "❌"
            tiago_badge = ""
            if plan.vehicle.is_tiago:
                tiago_badge = " 🏷️ <em>5ª viatura</em>"
            elif plan.tiago_supports:
                tiago_badge = " 🤝 <em>Tiago apoia (-10%)</em>"

            with st.expander(
                f"**{plan.vehicle.plate}** — {plan.vehicle.driver} | "
                f"{plan.total_clients} clientes, {plan.total_boxes} cx, "
                f"{plan.total_hours:.1f}h, {plan.total_km:.0f} km "
                f"{hours_icon}",
                expanded=False
            ):
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Clientes", plan.total_clients)
                c2.metric("Caixas", plan.total_boxes)
                c3.metric("Horas", f"{plan.total_hours:.1f}")
                c4.metric("Km", f"{plan.total_km:.0f}")
                c5.metric("Gasóleo", f"€{plan.fuel_cost:.2f}")

                st.markdown(f"**Zonas:** {', '.join(plan.zones)}")
                st.markdown(f"**Saída armazém:** {plan.departure_time} → **Último cliente:** {plan.last_client_departure} → **Casa:** {plan.arrival_home}")

                if tiago_badge:
                    st.markdown(tiago_badge, unsafe_allow_html=True)

                # Tabela de paragens
                stop_data = []
                for a in plan.stops:
                    tw_icon = ""
                    if a.stop.time_window_end:
                        if a.arrival_minutes <= a.stop.time_window_end:
                            tw_icon = "✅"
                        else:
                            tw_icon = "❌"

                    stop_data.append({
                        "Ordem": f"{a.delivery_order}/{a.total_stops}",
                        "Cliente": a.stop.client_name[:35],
                        "Cidade": a.stop.city,
                        "Caixas": a.stop.total_boxes,
                        "Chegada": a.estimated_arrival,
                        "Janela": a.stop.time_window_text or "—",
                        "": tw_icon,
                    })

                st.dataframe(stop_data, use_container_width=True, hide_index=True)

        st.divider()

        # ── Downloads ──
        st.subheader("📥 Download dos ficheiros")

        dl1, dl2, dl3 = st.columns(3)

        with dl1:
            with open(res['routed_path'], 'rb') as f:
                st.download_button(
                    label=f"📗 Mapa Picking Roteado",
                    data=f.read(),
                    file_name=f"MAPA_PICKING_{res.get('region','PORTO')}_{res['date_str']}_ROTEADO.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        with dl2:
            with open(res['precarga_path'], 'rb') as f:
                st.download_button(
                    label=f"📦 Mapa Pré-Carga",
                    data=f.read(),
                    file_name=f"MAPA_PRE_CARGA_{res.get('region','PORTO')}_{res['date_str']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        with dl3:
            guides_zip = generate_all_guides_zip(plans, exp_date, cfg)
            n_guides = len([p for p in plans if p.total_clients > 0])
            st.download_button(
                label=f"📄 Guias Motoristas ({n_guides} PDFs)",
                data=guides_zip,
                file_name=f"GUIAS_MOTORISTAS_{res.get('region','PORTO')}_{res['date_str']}.zip",
                mime="application/zip",
                use_container_width=True,
            )

        st.divider()

        # ── Mapa de rotas ──
        st.subheader("🗺️ Mapa de rotas")
        with st.spinner("A gerar mapa com rotas reais..."):
            map_html = generate_route_map(plans, cfg)

        import streamlit.components.v1 as components
        components.html(map_html, height=550, scrolling=False)

        st.download_button(
            label="🗺️ Download mapa (HTML interativo)",
            data=map_html,
            file_name=f"MAPA_ROTAS_{res.get('region','PORTO')}_{res['date_str']}.html",
            mime="text/html",
            use_container_width=True,
        )

        # ── Diagnóstico de geocodificação ──
        with st.expander("🔍 Diagnóstico de geocodificação", expanded=False):
            from engine.map_generator import _is_valid_coord
            geo_data = []
            for plan in plans:
                for a in plan.stops:
                    valid = _is_valid_coord(a.stop.lat, a.stop.lon)
                    geo_data.append({
                        "Motorista": plan.vehicle.driver,
                        "Cliente": a.stop.client_name[:25],
                        "Morada": (a.stop.address1 or '')[:30],
                        "CP": a.stop.postal_code or '',
                        "Cidade": a.stop.city or '',
                        "Lat": round(a.stop.lat, 5),
                        "Lon": round(a.stop.lon, 5),
                        "Estado": "✅" if valid else "❌ inválida",
                    })
            if geo_data:
                n_invalid = sum(1 for g in geo_data if "❌" in g["Estado"])
                if n_invalid > 0:
                    st.warning(f"⚠️ {n_invalid} paragens com coordenadas inválidas!")
                else:
                    st.success(f"✅ Todas as {len(geo_data)} paragens geocodificadas em Portugal")

                # Verificar duplicados (mesmas coordenadas)
                coords = [(g["Lat"], g["Lon"]) for g in geo_data]
                unique = len(set(coords))
                if unique < len(coords):
                    st.info(f"ℹ️ {len(coords) - unique} paragens partilham coordenadas (podem sobrepor-se no mapa)")

                st.dataframe(geo_data, use_container_width=True, hide_index=True)

    else:
        st.info("👆 Faz upload do ficheiro de picking e clica **Calcular Rotas** para começar.")


if __name__ == '__main__':
    main()
