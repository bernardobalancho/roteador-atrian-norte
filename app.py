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


st.set_page_config(
    page_title="Roteador Atrian Norte",
    page_icon="🚛",
    layout="wide",
)

# ── Password Gate ──
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "atrian2025")


def check_password():
    """Ecrã de login simples com password partilhada."""
    if st.session_state.get("authenticated"):
        return True

    st.markdown(
        """
        <div style="display:flex; flex-direction:column; align-items:center;
                    justify-content:center; padding-top:8rem;">
            <p style="font-size:3rem; margin-bottom:0;">🚛</p>
            <h2 style="margin-bottom:0.2rem;">Roteador Atrian Norte</h2>
            <p style="color:#888;">Introduz a password para aceder</p>
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


# ── CSS ──
st.markdown("""
<style>
    .main-title {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0;
    }
    .sub-title {
        font-size: 1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
        border-left: 4px solid #4472C4;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1a1a2e;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #666;
    }
    .vehicle-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.8rem;
    }
    .status-ok { color: #27ae60; font-weight: 600; }
    .status-warn { color: #f39c12; font-weight: 600; }
    .status-error { color: #e74c3c; font-weight: 600; }
    div[data-testid="stSidebar"] { background: #f0f2f6; }
    .stDownloadButton > button {
        width: 100%;
        background-color: #4472C4;
        color: white;
    }
</style>
""", unsafe_allow_html=True)


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


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

    config = load_config()

    # ── Header ──
    st.markdown('<p class="main-title">🚛 Roteador Atrian Norte</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Planeamento de rotas diário — zona Norte de Portugal</p>', unsafe_allow_html=True)

    # ── OSRM status ──
    if _check_osrm():
        st.success("🛰️ OSRM ativo — distâncias e tempos reais pela estrada")
    else:
        st.warning("⚠️ OSRM indisponível — a usar estimativa haversine como fallback")

    # ── Sidebar: configuração ──
    with st.sidebar:
        st.header("⚙️ Configuração")

        st.subheader("Frota ativa")
        fleet_active = {}
        for v in config['fleet']:
            fleet_active[v['plate']] = st.checkbox(
                f"{v['plate']} — {v['driver']}",
                value=v.get('active', True),
                key=f"fleet_{v['plate']}"
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
            st.caption("🛰️ Distâncias reais via OSRM (fator estrada não aplicável)")
        porto_reduction = st.slider("Redução Porto (%)", 0, 30, int(config.get('porto_time_reduction', 0.10) * 100))

    # Apply sidebar changes to config
    for v in config['fleet']:
        v['active'] = fleet_active.get(v['plate'], True)
    config['work_hours']['normal']['start'] = start_time
    config['work_hours']['reduced']['start'] = start_time
    config['work_hours']['normal']['max_hours'] = max_hours_normal
    config['work_hours']['reduced']['max_hours'] = max_hours_reduced
    config['road_factor'] = road_factor
    config['porto_time_reduction'] = porto_reduction / 100

    # ── Main content ──
    col_upload, col_criteria = st.columns(2)

    with col_upload:
        st.subheader("📋 Mapa de Picking")
        st.caption("Ficheiro Excel com as encomendas do dia")
        input1_file = st.file_uploader(
            "Upload Input 1",
            type=['xlsx'],
            key='input1',
            label_visibility='collapsed'
        )

    with col_criteria:
        st.subheader("📊 Critérios (opcional)")
        st.caption("Ficheiro com critérios, mapa de distribuição e matrículas")
        input2_file = st.file_uploader(
            "Upload Input 2",
            type=['xlsx'],
            key='input2',
            label_visibility='collapsed'
        )

    st.divider()

    # ── Botão de roteamento ──
    if input1_file is not None:
        run_button = st.button("🚀 Calcular Rotas", type="primary", use_container_width=True)

        if run_button:
            with st.spinner("A processar encomendas e a calcular rotas..."):
                try:
                    input1_path = save_uploaded_file(input1_file)
                    input2_path = save_uploaded_file(input2_file) if input2_file else None

                    lines, expedition_date = load_picking_map(input1_path)

                    if not expedition_date:
                        st.error("Não foi possível extrair a data de expedição do ficheiro.")
                        return

                    route_plans = route(lines, config, expedition_date)

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
                    }

                    os.unlink(input1_path)
                    if input2_path:
                        os.unlink(input2_path)

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

        st.markdown(f"### 📅 Expedição: {exp_date.strftime('%d/%m/%Y')} ({day_name})")

        if is_reduced:
            st.info(f"⏰ Dia com horário reduzido — máximo {max_h:.0f}h por motorista")

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
                st.metric("Janelas", "✅ OK")
            else:
                st.metric("Janelas", f"⚠️ {violations}")

        st.divider()

        # ── Detalhe por viatura ──
        st.subheader("🚛 Detalhe por viatura")

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

        dl1, dl2 = st.columns(2)

        with dl1:
            with open(res['routed_path'], 'rb') as f:
                st.download_button(
                    label=f"📗 Mapa Picking Roteado",
                    data=f.read(),
                    file_name=f"MAPA_PICKING_{res['date_str']}_ROTEADO.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        with dl2:
            with open(res['precarga_path'], 'rb') as f:
                st.download_button(
                    label=f"📦 Mapa Pré-Carga",
                    data=f.read(),
                    file_name=f"MAPA_PRE_CARGA_{res['date_str']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    else:
        st.info("👆 Faz upload do ficheiro de picking e clica **Calcular Rotas** para começar.")


if __name__ == '__main__':
    main()
