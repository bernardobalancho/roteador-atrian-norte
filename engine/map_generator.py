"""
Gerador de mapas interativos com as rotas dos motoristas.
Usa Folium (OpenStreetMap) + geometria real do OSRM.
"""
import folium
import requests
import io

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


def _get_route_geometry(points):
    """
    Obtem a geometria real da rota (polyline) via OSRM.

    Args:
        points: lista de (lat, lon)

    Returns:
        lista de (lat, lon) com todos os pontos da estrada, ou None
    """
    if len(points) < 2:
        return None

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
                # GeoJSON usa [lon, lat], converter para [lat, lon]
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

    # Criar mapa centrado no deposito
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

    # Gerar rota para cada motorista
    active_plans = [p for p in route_plans if p.total_clients > 0]

    for idx, plan in enumerate(active_plans):
        color = ROUTE_COLORS[idx % len(ROUTE_COLORS)]
        driver = plan.vehicle.driver
        plate = plan.vehicle.plate

        # Criar feature group para esta rota (toggle on/off)
        fg = folium.FeatureGroup(name=f"{driver} ({plate})")

        # Pontos da rota: deposito → paragens → casa do motorista
        route_points = [(depot_lat, depot_lon)]
        for a in plan.stops:
            route_points.append((a.stop.lat, a.stop.lon))
        route_points.append((plan.vehicle.home_lat, plan.vehicle.home_lon))

        # Obter geometria real da estrada via OSRM
        road_coords = _get_route_geometry(route_points)

        if road_coords:
            # Rota real pela estrada
            folium.PolyLine(
                road_coords,
                color=color,
                weight=4,
                opacity=0.8,
                tooltip=f"{driver}: {plan.total_clients} clientes, {plan.total_km:.0f}km"
            ).add_to(fg)
        else:
            # Fallback: linhas retas entre pontos
            folium.PolyLine(
                route_points,
                color=color,
                weight=3,
                opacity=0.6,
                dash_array='10',
                tooltip=f"{driver} (linha reta)"
            ).add_to(fg)

        # Marcadores das paragens
        for a in plan.stops:
            # Popup com detalhes
            popup_html = f"""
            <div style="font-family:Arial; min-width:180px;">
                <b style="color:{color};">{a.delivery_order}/{a.total_stops}</b>
                <b>{a.stop.client_name[:30]}</b><br>
                <small>{a.stop.city or ''}</small><br>
                <hr style="margin:4px 0;">
                <b>Motorista:</b> {driver}<br>
                <b>Chegada:</b> {a.estimated_arrival}<br>
                <b>Caixas:</b> {a.stop.total_boxes}<br>
                {f'<b>Janela:</b> {a.stop.time_window_text}<br>' if a.stop.time_window_text else ''}
            </div>
            """

            # Tooltip curto
            tooltip = f"{a.delivery_order}. {a.stop.client_name[:20]} ({a.estimated_arrival})"

            folium.CircleMarker(
                [a.stop.lat, a.stop.lon],
                radius=8,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=tooltip,
            ).add_to(fg)

            # Numero da paragem
            folium.Marker(
                [a.stop.lat, a.stop.lon],
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
        folium.Marker(
            [plan.vehicle.home_lat, plan.vehicle.home_lon],
            popup=f"<b>Casa {driver}</b><br>Chegada: {plan.arrival_home}",
            tooltip=f"Casa {driver}",
            icon=folium.Icon(color='gray', icon='home', prefix='fa')
        ).add_to(fg)

        fg.add_to(m)

    # Controlo de camadas (toggle motoristas)
    folium.LayerControl(collapsed=False).add_to(m)

    # Legenda
    legend_html = _build_legend(active_plans)
    m.get_root().html.add_child(folium.Element(legend_html))

    return m._repr_html_()


def _build_legend(plans):
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

    return f"""
    <div style="position:fixed; bottom:30px; left:10px; z-index:1000;
                background:white; padding:12px 16px; border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.3); font-size:12px;
                font-family:Arial; max-width:350px;">
        <b style="font-size:13px;">Rotas do dia</b>
        <hr style="margin:6px 0;">
        {items}
    </div>
    """
