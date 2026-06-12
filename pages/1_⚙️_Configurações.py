"""
Pagina de configuracoes editaveis.

Permite editar via UI tudo o que normalmente esta no config_<regiao>.yaml:
- Armazem
- Frota (motoristas, matriculas, casas, capacidades)
- Mapa de distribuicao (zonas x dias x motoristas preferenciais)
- Restricoes por motorista
- Horarios, tempos, ajustes
- Motorista de apoio
- Cidades especiais

Guarda via GitHub API (se token configurado) ou no disco local.
"""
import os
import sys
import copy
import yaml
import pandas as pd
import streamlit as st

# Permitir imports do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.config_storage import save_config, storage_mode


# ── Page config ──
st.set_page_config(
    page_title="Configurações — Atrian Logistics",
    page_icon="⚙️",
    layout="wide",
)

# ── Gate: tem de estar autenticado ──
if not st.session_state.get("authenticated"):
    st.error("🔒 Precisas de fazer login primeiro.")
    st.page_link("app.py", label="← Voltar ao login", icon="🔙")
    st.stop()


# ── Helpers ──
def load_config_file(region: str) -> dict:
    """Carrega config da regiao a partir do ficheiro YAML."""
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, f'config_{region.lower()}.yaml')
    if not os.path.exists(path):
        st.error(f"Ficheiro {path} nao encontrado")
        st.stop()
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def available_regions():
    base = os.path.dirname(os.path.dirname(__file__))
    regions = []
    for f in os.listdir(base):
        if f.startswith('config_') and f.endswith('.yaml'):
            regions.append(f[len('config_'):-len('.yaml')].capitalize())
    return sorted(regions)


DAY_NAMES = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']


# ── CSS (alinhar com tema dark da app principal) ──
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700&family=Hanken+Grotesk:wght@400;500&display=swap" rel="stylesheet">
<style>
    html, body, .stApp { background: #0A0A0A !important; color: #E2E2E2 !important; }
    h1, h2, h3, h4 { font-family: 'Montserrat', sans-serif !important; color: #E2E2E2 !important; }
    p, label, div { font-family: 'Hanken Grotesk', sans-serif !important; }
    .stButton > button[kind="primary"] {
        background: #BA0C2F !important; color: white !important;
        border: none !important; border-radius: 8px !important;
        font-family: 'Montserrat',sans-serif !important; font-weight: 600 !important;
    }
    section[data-testid="stSidebar"] { background: #1E1E1E !important; }
    div[data-testid="stExpander"] {
        background: #1E1E1E; border: 1px solid rgba(171,136,136,0.1) !important;
        border-radius: 12px !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Header ──
st.markdown("## ⚙️ Configurações")
st.caption("Edita os critérios, frota, zonas e restrições da região. "
           "Alterações guardadas via GitHub (cloud) ou no disco (local).")

mode = storage_mode()
if mode == 'github':
    st.info(f"💾 Modo de gravação: **GitHub API** — alterações persistem no Streamlit Cloud")
else:
    st.warning(f"💾 Modo de gravação: **Local** — alterações só persistem nesta máquina. "
               f"Para guardar no Streamlit Cloud, configura `GITHUB_TOKEN` nos secrets.")


# ── Region selector ──
regions = available_regions()
current_region = st.sidebar.selectbox(
    "🌍 Região a editar",
    regions,
    index=regions.index(st.session_state.get('region', 'Porto'))
          if st.session_state.get('region', 'Porto') in regions else 0,
    key='config_region_selector',
)

# Carregar config atual da regiao (com possibilidade de "Recarregar do disco")
reload_clicked = st.sidebar.button("🔄 Recarregar do ficheiro", use_container_width=True)
state_key = f'edit_config_{current_region}'

if state_key not in st.session_state or reload_clicked:
    st.session_state[state_key] = load_config_file(current_region)

cfg = st.session_state[state_key]
original = load_config_file(current_region)


# ============================================================
# SECÇÃO 1: Geral (região, armazém)
# ============================================================
with st.expander("🏢 Geral & Armazém", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        cfg['region'] = st.text_input("Nome da região", value=cfg.get('region', current_region))
        cfg['depot']['name'] = st.text_input(
            "Nome do armazém",
            value=cfg.get('depot', {}).get('name', ''),
        )
    with col2:
        cfg['depot']['lat'] = st.number_input(
            "Latitude do armazém",
            value=float(cfg.get('depot', {}).get('lat', 0)),
            format="%.6f", step=0.0001,
        )
        cfg['depot']['lon'] = st.number_input(
            "Longitude do armazém",
            value=float(cfg.get('depot', {}).get('lon', 0)),
            format="%.6f", step=0.0001,
        )


# ============================================================
# SECÇÃO 2: Horários e tempos
# ============================================================
with st.expander("⏱️ Horários, tempos e ajustes", expanded=False):
    st.markdown("**Horário normal (ter-sex)**")
    c1, c2 = st.columns(2)
    with c1:
        cfg['work_hours']['normal']['start'] = st.text_input(
            "Início (HH:MM)", value=cfg['work_hours']['normal']['start'], key='wh_n_start'
        )
    with c2:
        cfg['work_hours']['normal']['max_hours'] = st.number_input(
            "Máx. horas", value=float(cfg['work_hours']['normal']['max_hours']),
            step=0.5, min_value=1.0, max_value=14.0, key='wh_n_max'
        )

    st.markdown("**Horário reduzido (seg+sáb)**")
    c1, c2, c3 = st.columns(3)
    with c1:
        cfg['work_hours']['reduced']['start'] = st.text_input(
            "Início", value=cfg['work_hours']['reduced']['start'], key='wh_r_start'
        )
    with c2:
        cfg['work_hours']['reduced']['max_hours'] = st.number_input(
            "Máx. horas", value=float(cfg['work_hours']['reduced']['max_hours']),
            step=0.5, min_value=1.0, max_value=14.0, key='wh_r_max'
        )
    with c3:
        cfg['work_hours']['reduced']['end_by'] = st.text_input(
            "Fim até (HH:MM)",
            value=cfg['work_hours']['reduced'].get('end_by', '12:00'), key='wh_r_end'
        )

    st.divider()
    st.markdown("**Tempos de carga e descarga**")
    c1, c2 = st.columns(2)
    with c1:
        cfg['loading']['base_minutes'] = st.number_input(
            "Carga: minutos base", value=int(cfg['loading']['base_minutes']),
            step=5, min_value=0, key='ld_base'
        )
        cfg['loading']['base_clients'] = st.number_input(
            "Carga: clientes incluídos no base", value=int(cfg['loading']['base_clients']),
            step=1, min_value=1, key='ld_clients'
        )
        cfg['loading']['extra_minutes_per_client'] = st.number_input(
            "Carga: min/cliente extra", value=int(cfg['loading']['extra_minutes_per_client']),
            step=1, min_value=0, key='ld_extra'
        )
    with c2:
        cfg['unloading']['base_minutes'] = st.number_input(
            "Descarga: minutos base", value=int(cfg['unloading']['base_minutes']),
            step=1, min_value=0, key='ul_base'
        )
        cfg['unloading']['threshold_boxes'] = st.number_input(
            "Descarga: limite caixas base", value=int(cfg['unloading']['threshold_boxes']),
            step=1, min_value=1, key='ul_thr'
        )
        cfg['unloading']['extra_minutes'] = st.number_input(
            "Descarga: min extra por intervalo", value=int(cfg['unloading']['extra_minutes']),
            step=1, min_value=0, key='ul_extra'
        )
        cfg['unloading']['interval_size'] = st.number_input(
            "Descarga: tamanho intervalo (caixas)", value=int(cfg['unloading']['interval_size']),
            step=1, min_value=1, key='ul_int'
        )

    st.divider()
    st.markdown("**Ajustes de tempo**")
    c1, c2, c3 = st.columns(3)
    with c1:
        cfg['city_time_adjustment'] = st.slider(
            "Ajuste cidade especial (%)",
            min_value=-30, max_value=30,
            value=int(cfg.get('city_time_adjustment', 0) * 100), step=1,
            help="Negativo = reduz tempo no centro; positivo = aumenta (trânsito)"
        ) / 100
    with c2:
        cfg['unforeseen_tolerance'] = st.slider(
            "Tolerância imponderáveis (%)",
            min_value=0, max_value=30,
            value=int(cfg.get('unforeseen_tolerance', 0) * 100), step=1,
            help="Aplicado a cada deslocação (Lisboa: 5%)"
        ) / 100
    with c3:
        cfg['support_driver_reduction'] = st.slider(
            "Redução motorista apoio (%)",
            min_value=0, max_value=30,
            value=int(cfg.get('support_driver_reduction', 0.10) * 100), step=1,
            help="Quando motorista apoia outro, descarga reduz X%"
        ) / 100


# ============================================================
# SECÇÃO 3: Motorista de apoio e cidades especiais
# ============================================================
with st.expander("🤝 Motorista de apoio + cidades especiais", expanded=False):
    fleet_names = [v['driver'] for v in cfg.get('fleet', [])]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Motorista de apoio**")
        sup = cfg.get('support_driver') or {}
        current_name = sup.get('driver_name', '')
        options = [''] + fleet_names
        idx = options.index(current_name) if current_name in options else 0
        new_sup = st.selectbox(
            "Quem é a viatura de apoio?",
            options, index=idx,
            help="Motorista que apoia outros em vez de fazer a sua rota se possível"
        )
        if 'support_driver' not in cfg or cfg['support_driver'] is None:
            cfg['support_driver'] = {}
        cfg['support_driver']['driver_name'] = new_sup
        cfg['support_driver']['display_name'] = st.text_input(
            "Nome curto (para mensagens)",
            value=sup.get('display_name', new_sup.split()[0] if new_sup else '')
        )
        cfg['support_driver']['max_hours_threshold'] = st.number_input(
            "Só sair se outros excederem (h)",
            value=float(sup.get('max_hours_threshold', 9.0)), step=0.5,
        )

    with c2:
        st.markdown("**Cidades com ajuste de tempo de descarga**")
        cities_str = "\n".join(cfg.get('special_cities', ['PORTO']))
        new_cities = st.text_area(
            "Uma por linha",
            value=cities_str,
            height=120,
            help="Em maiúsculas. Ex: PORTO, LISBOA. Aplica-se o ajuste % acima a entregas nestas cidades."
        )
        cfg['special_cities'] = [c.strip().upper() for c in new_cities.split('\n')
                                  if c.strip()]


# ============================================================
# SECÇÃO 4: Frota (tabela editável)
# ============================================================
with st.expander("🚛 Frota de motoristas", expanded=True):
    st.caption("Adiciona/remove linhas com os botões. **Ativo=False** desativa o motorista.")

    fleet_df = pd.DataFrame([{
        'plate': v.get('plate', ''),
        'driver': v.get('driver', ''),
        'active': v.get('active', True),
        'home_city': v.get('home_city', ''),
        'home_lat': float(v.get('home_lat', 0)),
        'home_lon': float(v.get('home_lon', 0)),
        'max_volume_m3': float(v.get('max_volume_m3', 10)),
        'max_boxes': int(v.get('max_boxes', 200)),
        'priority': int(v.get('priority', 99)),
    } for v in cfg.get('fleet', [])])

    edited_fleet = st.data_editor(
        fleet_df,
        num_rows='dynamic',
        use_container_width=True,
        column_config={
            'plate': st.column_config.TextColumn("Matrícula", required=True),
            'driver': st.column_config.TextColumn("Motorista", required=True),
            'active': st.column_config.CheckboxColumn("Ativo", default=True),
            'home_city': st.column_config.TextColumn("Casa (cidade)"),
            'home_lat': st.column_config.NumberColumn("Lat", format="%.4f"),
            'home_lon': st.column_config.NumberColumn("Lon", format="%.4f"),
            'max_volume_m3': st.column_config.NumberColumn("Vol. m³", format="%.1f"),
            'max_boxes': st.column_config.NumberColumn("Máx. caixas"),
            'priority': st.column_config.NumberColumn("Prioridade",
                help="1 = sempre sai; 5 = só sai se necessário (motorista de apoio)"),
        },
        key='fleet_editor',
        hide_index=True,
    )

    # Aplicar de volta ao config
    new_fleet = []
    for _, row in edited_fleet.iterrows():
        if not row.get('plate') or not row.get('driver'):
            continue
        new_fleet.append({
            'plate': str(row['plate']).strip(),
            'driver': str(row['driver']).strip(),
            'active': bool(row['active']),
            'home_city': str(row.get('home_city', '')),
            'home_lat': float(row.get('home_lat', 0)),
            'home_lon': float(row.get('home_lon', 0)),
            'max_volume_m3': float(row.get('max_volume_m3', 10)),
            'max_boxes': int(row.get('max_boxes', 200)),
            'priority': int(row.get('priority', 99)),
        })
    cfg['fleet'] = sorted(new_fleet, key=lambda v: v['priority'])


# ============================================================
# SECÇÃO 5: Mapa de distribuição (zonas × dias × motoristas)
# ============================================================
with st.expander("📅 Mapa de distribuição (zonas × dias × motoristas)", expanded=True):
    st.caption("Marca os dias em que cada zona é distribuída e quais motoristas a fazem (por ordem de preferência).")

    fleet_names = [v['driver'] for v in cfg.get('fleet', [])]
    dm = cfg.get('distribution_map', {})

    zones_df = pd.DataFrame([{
        'zona': name,
        'Seg': 0 in info.get('days', []),
        'Ter': 1 in info.get('days', []),
        'Qua': 2 in info.get('days', []),
        'Qui': 3 in info.get('days', []),
        'Sex': 4 in info.get('days', []),
        'Sáb': 5 in info.get('days', []),
        'motoristas': ', '.join(info.get('preferred_drivers', [])),
    } for name, info in dm.items()])

    edited_zones = st.data_editor(
        zones_df,
        num_rows='dynamic',
        use_container_width=True,
        column_config={
            'zona': st.column_config.TextColumn("Zona", required=True, width="large"),
            'Seg': st.column_config.CheckboxColumn("Seg"),
            'Ter': st.column_config.CheckboxColumn("Ter"),
            'Qua': st.column_config.CheckboxColumn("Qua"),
            'Qui': st.column_config.CheckboxColumn("Qui"),
            'Sex': st.column_config.CheckboxColumn("Sex"),
            'Sáb': st.column_config.CheckboxColumn("Sáb"),
            'motoristas': st.column_config.TextColumn(
                "Motoristas preferenciais (por ordem, separados por vírgula)",
                help="Ex: BRUNO, PAULO — o primeiro tem prioridade", width="large"
            ),
        },
        key='zones_editor',
        hide_index=True,
    )

    new_dm = {}
    for _, row in edited_zones.iterrows():
        zone = str(row.get('zona', '')).strip()
        if not zone:
            continue
        days = []
        for idx, day in enumerate(['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']):
            if row.get(day, False):
                days.append(idx)
        drivers = [d.strip() for d in str(row.get('motoristas', '')).split(',')
                   if d.strip()]
        new_dm[zone] = {
            'days': days,
            'preferred_drivers': drivers,
        }
    cfg['distribution_map'] = new_dm


# ============================================================
# SECÇÃO 6: Restrições por motorista
# ============================================================
with st.expander("🚫 Restrições por motorista", expanded=False):
    st.caption("Zonas/cidades que cada motorista deve evitar.")

    restrictions = cfg.get('driver_restrictions', {})
    all_zones = list(cfg.get('distribution_map', {}).keys())

    rest_rows = []
    for drv_name, rest in restrictions.items():
        rest_rows.append({
            'motorista': drv_name,
            'evitar_zonas': ', '.join(rest.get('avoid_zones', [])),
            'evitar_cidades': ', '.join(rest.get('avoid_cities', [])),
        })

    if not rest_rows:
        rest_rows = [{'motorista': '', 'evitar_zonas': '', 'evitar_cidades': ''}]

    rest_df = pd.DataFrame(rest_rows)
    edited_rest = st.data_editor(
        rest_df,
        num_rows='dynamic',
        use_container_width=True,
        column_config={
            'motorista': st.column_config.TextColumn("Motorista", required=True),
            'evitar_zonas': st.column_config.TextColumn(
                "Zonas a evitar (separadas por vírgula)", width="large"),
            'evitar_cidades': st.column_config.TextColumn(
                "Cidades a evitar (separadas por vírgula)", width="medium"),
        },
        key='rest_editor',
        hide_index=True,
    )

    new_rest = {}
    for _, row in edited_rest.iterrows():
        name = str(row.get('motorista', '')).strip()
        if not name:
            continue
        zones = [z.strip() for z in str(row.get('evitar_zonas', '')).split(',')
                 if z.strip()]
        cities = [c.strip() for c in str(row.get('evitar_cidades', '')).split(',')
                  if c.strip()]
        entry = {}
        if zones:
            entry['avoid_zones'] = zones
        if cities:
            entry['avoid_cities'] = cities
        if entry:
            new_rest[name] = entry
    cfg['driver_restrictions'] = new_rest


# ============================================================
# SECÇÃO 7: Diff & Save
# ============================================================
st.divider()
st.markdown("### 💾 Guardar alterações")

# Calcular se há mudanças
import io
buf_a = io.StringIO()
buf_b = io.StringIO()
yaml.safe_dump(original, buf_a, allow_unicode=True, sort_keys=False)
yaml.safe_dump(cfg, buf_b, allow_unicode=True, sort_keys=False)
has_changes = buf_a.getvalue() != buf_b.getvalue()

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    if has_changes:
        st.warning("⚠️ Há alterações por guardar.")
    else:
        st.success("✅ Sem alterações pendentes.")

with c2:
    if st.button("🔄 Descartar alterações", use_container_width=True,
                  disabled=not has_changes):
        st.session_state.pop(state_key, None)
        st.rerun()

with c3:
    if st.button("💾 Guardar", type="primary", use_container_width=True,
                  disabled=not has_changes):
        with st.spinner(f"A guardar config_{current_region.lower()}.yaml..."):
            result = save_config(current_region, cfg, user_label="Atrian UI")
        if result['success']:
            st.success(f"✅ {result['message']}")
            if result.get('commit_url'):
                st.markdown(f"🔗 [Ver commit no GitHub]({result['commit_url']})")
            st.balloons()
        else:
            st.error(f"❌ {result['message']}")


# ── Preview YAML final ──
with st.expander("📄 Preview do YAML que será guardado", expanded=False):
    st.code(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False,
                           default_flow_style=False, indent=2),
            language='yaml')

with st.expander("📥 Download como ficheiro YAML", expanded=False):
    st.download_button(
        f"⬇️ Download config_{current_region.lower()}.yaml",
        data=yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False,
                            default_flow_style=False, indent=2),
        file_name=f"config_{current_region.lower()}.yaml",
        mime="application/x-yaml",
        use_container_width=True,
    )
