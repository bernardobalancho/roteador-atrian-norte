"""
Gerador de mapas interativos com as rotas dos motoristas.
Usa Folium (OpenStreetMap) + geometria real do OSRM.
"""
import folium
import requests

# Cores distintas para cada motorista
ROUTE_COLORS = [
    '#e6194b',  # vermelho
    '#3cb44b',  # verde
    '#4363d8',  # azul
    '#f58231',  # laranja
    '#911eb4',  # roxo
    '#42d4f4',  # ciano
    '#f032e6',  # magenta
    '#bfef45',  # lima
]

OSRM_BASE = "https://router.project-osrm.org"


def _is_valid_coord(lat, lon):
    """Verifica se as coordenadas sao validas (em Portugal continental)."""
    return (36.0 < lat < 43.0 and -10.0 < lon < -6.0)


def _get_route_geometry(points):
    """
    Obtem a geometria real da rota (polyline) via OSRM.
    Divide em segmentos se houver muitos pontos.

    Args:
        points: lista de (lat, lon) — ja filtrados (sem coords invalidas)

    Returns:
        lista de (lat, lon) com todos os pontos da estrada, ou None
    """
    if len(points) < 2:
        return None

    # Filtrar pontos invalidos
    valid_points = [(lat, lon) for lat, lon in points if _is_valid_coord(lat, lon)]
    if len(valid_points) < 2:
        return None

    # OSRM pode ter limites de waypoints — dividir em segmentos de 25
    MAX_WAYPOINTS = 25
    if len(valid_points) <= MAX_WAYPOINTS:
        return _osrm_route_geometry(valid_points)

    # Dividir em segmentos sobrepostos
    all_coords = []
    for i in range(0, len(valid_points) - 1, MAX_WAYPOINTS - 1):
        segment = valid_points[i:i + MAX_WAYPOINTS]
        if len(segment) < 2:
            break
        seg_coords = _osrm_route_geometry(segment)
        if seg_coords:
            if all_coords:
                all_coords.extend(seg_coords[1:])  # evitar ponto duplicado
            else:
                all_coords = seg_coords
        else:
            # Fallback: linhas retas para este segmento
            if all_coords:
                all_coords.extend(segment[1:])
            else:
                all_coords = list(segment)

    return all_coords if len(all_coords) >= 2 else None


def _osrm_route_geometry(points):
    """Faz um pedido OSRM para obter geometria da rota."""
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    url = f"{OSRM_BASE}/route/v1/driving/{coords}"

    try:
        r = requests.get(url, params={
            "overview": "full",
            "geometries": "geojson",
            "steps": "false"
        }, timeout=15)

        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "Ok" and data.get("routes"):
                geojson = data["routes"][0]["geometry"]
                return [(c[1], c[0]) for c in geojson["coordinates"]]
    except Exception:
        pass

    return None


def generate_route_map(route_plans, config):
    """
    Gera um mapa interativo com todas as rotas do dia.

    Args:
        route_plans: lista de RoutePlan
        config: configuracao (para o deposito)

    Returns:
        str: HTML do mapa (para embed no Streamlit ou download)
    """
    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']
    depot_name = config['depot'].get('name', 'Armazem')

    # Criar mapa centrado no deposito (zoom sera ajustado depois)
    m = folium.Map(
        location=[depot_lat, depot_lon],
        zoom_start=10,
        tiles='OpenStreetMap'
    )

    # Marcador do deposito
    folium.Marker(
        [depot_lat, depot_lon],
        popup=f"<b>{depot_name}</b><br>Armazem de partida",
        tooltip=depot_name,
        icon=folium.Icon(color='black', icon='warehouse', prefix='fa')
    ).add_to(m)

    # Recolher todos os pontos para auto-zoom
    all_latlons = [(depot_lat, depot_lon)]

    # Contadores de diagnostico
    total_stops = 0
    invalid_stops = 0
    osrm_ok = 0
    osrm_fail = 0

    # Gerar rota para cada motorista
    active_plans = [p for p in route_plans if p.total_clients > 0]

    for idx, plan in enumerate(active_plans):
        color = ROUTE_COLORS[idx % len(ROUTE_COLORS)]
        driver = plan.vehicle.driver
        plate = plan.vehicle.plate

        # Criar feature group para esta rota (toggle on/off)
        fg = folium.FeatureGroup(name=f"{driver} ({plate})")

        # Pontos da rota: deposito -> paragens -> casa do motorista
        route_points = [(depot_lat, depot_lon)]
        skipped_stops = []

        for a in plan.stops:
            total_stops += 1
            if _is_valid_coord(a.stop.lat, a.stop.lon):
                route_points.append((a.stop.lat, a.stop.lon))
                all_latlons.append((a.stop.lat, a.stop.lon))
            else:
                invalid_stops += 1
                skipped_stops.append(a)

        # Adicionar casa do motorista
        if _is_valid_coord(plan.vehicle.home_lat, plan.vehicle.home_lon):
            route_points.append((plan.vehicle.home_lat, plan.vehicle.home_lon))
            all_latlons.append((plan.vehicle.home_lat, plan.vehicle.home_lon))

        # Obter geometria real da estrada via OSRM
        road_coords = _get_route_geometry(route_points)

        if road_coords:
            osrm_ok += 1
            folium.PolyLine(
                road_coords,
                color=color,
                weight=4,
                opacity=0.8,
                tooltip=f"{driver}: {plan.total_clients} clientes, {plan.total_km:.0f}km"
            ).add_to(fg)
        else:
            osrm_fail += 1
            # Fallback: linhas retas entre pontos
            folium.PolyLine(
                route_points,
                color=color,
                weight=3,
                opacity=0.6,
                dash_array='10',
                tooltip=f"{driver} (linha reta — OSRM indisponivel)"
            ).add_to(fg)

        # Marcadores das paragens (TODAS, incluindo as com coords invalidas)
        for a in plan.stops:
            has_valid = _is_valid_coord(a.stop.lat, a.stop.lon)

            # Popup com detalhes e info de diagnostico
            coord_info = f"({a.stop.lat:.4f}, {a.stop.lon:.4f})"
            if not has_valid:
                coord_info = f"<span style='color:red;'>⚠️ COORD INVALIDA {coord_info}</span>"

            popup_html = f"""
            <div style="font-family:Arial; min-width:200px;">
                <b style="color:{color};">{a.delivery_order}/{a.total_stops}</b>
                <b>{a.stop.client_name[:30]}</b><br>
                <small>{a.stop.address1 or ''}</small><br>
                <small>{a.stop.postal_code or ''} {a.stop.city or ''}</small><br>
                <hr style="margin:4px 0;">
                <b>Motorista:</b> {driver}<br>
                <b>Zona:</b> {a.stop.zone_name}<br>
                <b>Chegada:</b> {a.estimated_arrival}<br>
                <b>Caixas:</b> {a.stop.total_boxes}<br>
                {f'<b>Janela:</b> {a.stop.time_window_text}<br>' if a.stop.time_window_text else ''}
                <small style="color:#888;">{coord_info}</small>
            </div>
            """

            tooltip = f"{a.delivery_order}. {a.stop.client_name[:20]} ({a.estimated_arrival})"

            # Se coords invalidas, colocar no depot com marcador de aviso
            marker_lat = a.stop.lat if has_valid else depot_lat
            marker_lon = a.stop.lon if has_valid else depot_lon

            if has_valid:
                folium.CircleMarker(
                    [marker_lat, marker_lon],
                    radius=8,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.7,
                    popup=folium.Popup(popup_html, max_width=280),
                    tooltip=tooltip,
                ).add_to(fg)
            else:
                # Marcador especial para coords invalidas
                folium.CircleMarker(
                    [marker_lat, marker_lon],
                    radius=10,
                    color='red',
                    fill=True,
                    fill_color='red',
                    fill_opacity=0.9,
                    popup=folium.Popup(popup_html, max_width=280),
                    tooltip=f"⚠️ {tooltip} (coord invalida)",
                ).add_to(fg)

            # Numero da paragem
            folium.Marker(
                [marker_lat, marker_lon],
                icon=folium.DivIcon(
                    html=f'<div style="font-size:10px; font-weight:bold; color:white; '
                         f'background:{color}; border-radius:50%; width:18px; height:18px; '
                         f'text-align:center; line-height:18px; margin-left:-9px; margin-top:-9px;">'
                         f'{a.delivery_order}</div>',
                    icon_size=(18, 18),
                    icon_anchor=(0, 0),
                )
            ).add_to(fg)

        # Casa do motorista
        if _is_valid_coord(plan.vehicle.home_lat, plan.vehicle.home_lon):
            folium.Marker(
                [plan.vehicle.home_lat, plan.vehicle.home_lon],
                popup=f"<b>Casa {driver}</b><br>Chegada: {plan.arrival_home}",
                tooltip=f"Casa {driver}",
                icon=folium.Icon(color='gray', icon='home', prefix='fa')
            ).add_to(fg)

        fg.add_to(m)

    # ── Auto-zoom para incluir TODOS os pontos ──
    if len(all_latlons) > 1:
        lats = [p[0] for p in all_latlons]
        lons = [p[1] for p in all_latlons]
        m.fit_bounds([
            [min(lats) - 0.02, min(lons) - 0.02],
            [max(lats) + 0.02, max(lons) + 0.02]
        ])

    # Controlo de camadas (toggle motoristas)
    folium.LayerControl(collapsed=False).add_to(m)

    # Legenda com diagnostico
    legend_html = _build_legend(active_plans, total_stops, invalid_stops,
                                osrm_ok, osrm_fail)
    m.get_root().html.add_child(folium.Element(legend_html))

    return m._repr_html_()


def _build_legend(plans, total_stops=0, invalid_stops=0,
                  osrm_ok=0, osrm_fail=0):
    """Constroi HTML da legenda do mapa."""
    items = ""
    for idx, plan in enumerate(plans):
        color = ROUTE_COLORS[idx % len(ROUTE_COLORS)]
        items += f"""
        <div style="margin-bottom:4px;">
            <span style="background:{color}; width:12px; height:12px;
                         display:inline-block; border-radius:2px; margin-right:6px;"></span>
            <b>{plan.vehicle.driver}</b> ({plan.vehicle.plate})
            — {plan.total_clients} cl, {plan.total_boxes} cx, {plan.total_km:.0f}km, {plan.total_hours:.1f}h
        </div>
        """

    # Info de diagnostico
    diag = ""
    if invalid_stops > 0:
        diag = f"""
        <hr style="margin:6px 0;">
        <div style="color:red; font-size:11px;">
            ⚠️ {invalid_stops}/{total_stops} paragens com coordenadas invalidas
        </div>
        """
    if osrm_fail > 0:
        diag += f"""
        <div style="color:orange; font-size:11px;">
            ⚠️ {osrm_fail} rotas sem geometria OSRM (linhas retas)
        </div>
        """

    return f"""
    <div style="position:fixed; bottom:30px; left:10px; z-index:1000;
                background:white; padding:12px 16px; border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.3); font-size:12px;
                font-family:Arial; max-width:380px;">
        <b style="font-size:13px;">Rotas do dia</b>
        <hr style="margin:6px 0;">
        {items}
        {diag}
    </div>
    """
