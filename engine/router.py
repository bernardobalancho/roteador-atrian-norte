"""
Motor de roteamento.

Fluxo:
  1. Agrupa linhas de picking em paragens (stops)
  2. Geocodifica cada paragem
  3. Extrai janelas horarias
  4. Atribui paragens a viaturas (regras de negocio)
  5. Sequencia paragens dentro de cada viatura (OR-Tools TSP)
  6. Calcula tempos detalhados
  7. Aplica logica do Tiago
"""
import re
import math
from datetime import datetime
from collections import defaultdict
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from .models import PickingLine, Stop, Vehicle, AssignedStop, RoutePlan
from .geo import (geocode_postal, estimate_distance_km, estimate_travel_minutes,
                   osrm_table, _check_osrm, haversine_km)


def _get_traffic_multiplier(clock_minutes, lat1, lon1, lat2, lon2, config):
    """
    Devolve o multiplicador de transito baseado na hora e tipo de trajeto.

    O tipo de trajeto e determinado pela distancia REAL (OSRM) vs distancia
    em linha reta. Se a rota real e muito maior que a linha reta, e uma
    zona urbana com muitas curvas/ruas. Se e similar, e autoestrada direta.

    Classificacao:
      - urbano: rota real < 15 km (entregas dentro da mesma cidade)
      - suburbano: 15-40 km (cidades proximas, estradas nacionais)
      - intercidade: >40 km (autoestrada, longas distancias)

    Args:
        clock_minutes: minutos desde meia-noite (ex: 510 = 08:30)
        lat1, lon1: ponto de origem
        lat2, lon2: ponto de destino
        config: configuracao com traffic_profiles

    Returns:
        float: multiplicador (ex: 1.35 para +35% de transito)
    """
    profiles = config.get('traffic_profiles', {})
    bands = profiles.get('bands', [])
    if not bands:
        return 1.0

    # Usar distancia real (OSRM) para classificar o trajeto
    from .geo import osrm_route, _check_osrm
    real_km = None
    if _check_osrm():
        result = osrm_route(lat1, lon1, lat2, lon2)
        if result:
            real_km = result[0]

    if real_km is None:
        # Fallback: haversine × road_factor
        real_km = haversine_km(lat1, lon1, lat2, lon2) * config.get('road_factor', 1.35)

    # Classificar por distancia real pela estrada
    if real_km < 15:
        leg_type = 'urban'
    elif real_km < 40:
        leg_type = 'suburban'
    else:
        leg_type = 'intercity'

    # Encontrar banda horaria correspondente
    for band in bands:
        bh, bm = map(int, band['start'].split(':'))
        eh, em = map(int, band['end'].split(':'))
        band_start = bh * 60 + bm
        band_end = eh * 60 + em
        if band_start <= clock_minutes < band_end:
            factor = band.get(leg_type, 0)
            return 1.0 + factor

    return 1.0  # Fora de todas as bandas (ex: antes das 6h) = sem ajuste


def _parse_time(text):
    """Extrai hora em minutos desde 00:00 a partir de texto."""
    if not text:
        return None
    m = re.search(r'(\d{1,2})[hH:](\d{0,2})', str(text))
    if m:
        h = int(m.group(1))
        mins = int(m.group(2)) if m.group(2) else 0
        return h * 60 + mins
    return None


def _extract_time_window(address2, obs_external):
    """
    Extrai janela horaria de Morada 2 e Obs. externas.
    Devolve (start_min, end_min, text) ou (None, None, "").

    So extrai janelas de campos que contenham palavras-chave de entrega/horario.
    Morada 2 so e analisada se contiver termos como ENTREGA, HORA, ATE, PELAS.
    """
    sources = []
    # Obs. externas: analisar sempre (e para observacoes)
    obs = str(obs_external or '').strip()
    if obs and obs != '0':
        sources.append(obs)

    # Morada 2: so analisar se contiver keywords de horario
    addr2 = str(address2 or '').strip()
    if addr2 and addr2 != '0':
        addr2_upper = addr2.upper()
        time_keywords = ['ENTREGA', 'HORA', 'ATÉ', 'ATE', 'PELAS', 'ANTES',
                         'ENTRE', 'MANHÃ', 'MANHA', 'TARDE']
        if any(kw in addr2_upper for kw in time_keywords):
            sources.append(addr2)

    for text in sources:
        text_upper = text.upper().strip()
        if not text_upper:
            continue

        # "ENTRE AS 8H E AS 11H" / "entre as 10h30 e as 13h30"
        m = re.search(r'ENTRE\s+[AO]?S?\s*(\d{1,2})[hH:](\d{0,2})\s+E\s+[AO]?S?\s*(\d{1,2})[hH:](\d{0,2})', text_upper)
        if m:
            start = int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
            end = int(m.group(3)) * 60 + (int(m.group(4)) if m.group(4) else 0)
            tw_text = f"{m.group(1)}:{m.group(2) or '00'}-{m.group(3)}:{m.group(4) or '00'}"
            return start, end, tw_text

        # "08:00-11:00" ou "8H-11H" ou "8H00-11H00" — require H or : marker
        m = re.search(r'(\d{1,2})[hH:](\d{0,2})\s*[-]\s*(\d{1,2})[hH:](\d{0,2})', text_upper)
        if m:
            start = int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
            end = int(m.group(3)) * 60 + (int(m.group(4)) if m.group(4) else 0)
            if 4 <= start // 60 <= 23 and 4 <= end // 60 <= 23:
                clean = re.search(r'[\d]{1,2}[hH:]?\d{0,2}\s*[-]\s*[\d]{1,2}[hH:]?\d{0,2}', text)
                tw_text = clean.group(0) if clean else text.strip()
                return start, end, tw_text

        # "ATE 13H" / "até 13:00" / "até 11h"
        m = re.search(r'AT[EÉ]\s+[ÀA]?S?\s*(\d{1,2})[hH:]?(\d{0,2})', text_upper)
        if m:
            end = int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
            tw_text = f"até {m.group(1)}:{m.group(2) or '00'}"
            return None, end, tw_text

        # "DAS 9H ÀS 12H" / "7h às 16h" / "das 8H as 11H"
        m = re.search(r'(?:DAS?\s+)?(\d{1,2})[hH:]?(\d{0,2})\s+[ÀA]S\s+(\d{1,2})[hH:]?(\d{0,2})', text_upper)
        if m:
            start = int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
            end = int(m.group(3)) * 60 + (int(m.group(4)) if m.group(4) else 0)
            if 4 <= start // 60 <= 23 and 4 <= end // 60 <= 23:
                tw_text = f"{m.group(1)}:{m.group(2) or '00'}-{m.group(3)}:{m.group(4) or '00'}"
                return start, end, tw_text

        # "PELAS 10H" / "antes das 09h" / "ÀS 14H" (standalone, not part of range)
        m = re.search(r'(?:PELAS|ANTES\s+DAS?)\s+(\d{1,2})[hH:]?(\d{0,2})', text_upper)
        if not m:
            # "ÀS 14H" only if NOT preceded by a number (avoid matching "9H ÀS 12H")
            m = re.search(r'(?<!\d[hH]\s)[ÀA]S\s+(\d{1,2})[hH:]?(\d{0,2})', text_upper)
        if m:
            end = int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
            if 6 <= end // 60 <= 20:
                tw_text = f"{m.group(1)}:{m.group(2) or '00'}"
                return None, end, tw_text

        # "ENTREGAS 10-15H" / "8-11H"
        m = re.search(r'(?:ENTREGAS?\s+)?(\d{1,2})\s*[-]\s*(\d{1,2})[hH]', text_upper)
        if m:
            start = int(m.group(1)) * 60
            end = int(m.group(2)) * 60
            return start, end, f"{m.group(1)}:00-{m.group(2)}:00"

        # Bare time: "09:00-12:00" or "07:00-16:00" (with colon, not in address context)
        m = re.search(r'(\d{2}):(\d{2})\s*[-/]\s*(\d{2}):(\d{2})', text_upper)
        if m:
            start = int(m.group(1)) * 60 + int(m.group(2))
            end = int(m.group(3)) * 60 + int(m.group(4))
            if 4 <= start // 60 <= 23 and 4 <= end // 60 <= 23:
                return start, end, f"{m.group(1)}:{m.group(2)}-{m.group(3)}:{m.group(4)}"

        # "10:00" or "14:00" or "14:30" standalone time (from obs_external)
        m = re.match(r'^(\d{1,2}):(\d{2})$', text_upper.strip())
        if m:
            t = int(m.group(1)) * 60 + int(m.group(2))
            if 6 <= t // 60 <= 20:
                tw_text = f"{m.group(1)}:{m.group(2)}"
                return None, t, tw_text

    return None, None, ""


def _map_zone(route_code, zone_map):
    """Mapeia codigo de rota para nome de zona."""
    if not route_code:
        return "Desconhecida"
    for prefix, zone_name in zone_map.items():
        if route_code.startswith(prefix) or prefix in route_code:
            return zone_name
    parts = route_code.split(' ', 1)
    if len(parts) > 1:
        return parts[1]
    return route_code


def build_stops(lines, config):
    """
    Agrupa linhas de picking em paragens.
    Uma paragem = combinacao unica de (cliente + end. expedicao).
    """
    zone_map = config.get('zone_map', {})
    # Cidades com ajuste de tempo de descarga (Porto: -10%, Lisboa: +5%)
    # Backward compat: aceita 'special_cities' (novo) ou 'porto_cities' (legacy)
    special_cities = [c.upper() for c in
                      config.get('special_cities',
                                 config.get('porto_cities', ['PORTO']))]
    stops_dict = {}

    for line in lines:
        key = f"{line.client_code}_{line.shipping_address}"
        if key not in stops_dict:
            lat, lon = geocode_postal(line.postal_code, line.city, line.address1)
            zone = _map_zone(line.route_code, zone_map)
            tw_start, tw_end, tw_text = _extract_time_window(line.address2, line.obs_external)

            stops_dict[key] = Stop(
                stop_id=key,
                client_code=line.client_code,
                client_name=line.client_name,
                shipping_address=line.shipping_address,
                address1=line.address1,
                postal_code=line.postal_code,
                city=line.city,
                route_code=line.route_code,
                zone_name=zone,
                lat=lat,
                lon=lon,
                time_window_start=tw_start,
                time_window_end=tw_end,
                time_window_text=tw_text,
                pre_assigned_plate=line.transporter or "",
                is_porto=line.city.upper().strip() in special_cities if line.city else False,
            )

        stop = stops_dict[key]
        stop.lines.append(line)
        stop.total_boxes += line.quantity
        stop.total_weight += line.weight
        vol = line.height * line.width * line.depth * line.quantity
        stop.total_volume += vol

    for stop in stops_dict.values():
        stop.unload_minutes = _calc_unload_time(stop.total_boxes, config)

    return list(stops_dict.values())


def _calc_unload_time(boxes, config):
    """Calcula tempo de descarga em minutos."""
    uc = config['unloading']
    base = uc['base_minutes']
    if boxes <= uc['threshold_boxes']:
        return base
    extra_intervals = math.ceil((boxes - uc['threshold_boxes']) / uc['interval_size'])
    return base + extra_intervals * uc['extra_minutes']


def build_vehicles(config):
    """Constroi lista de viaturas a partir do config."""
    # Nome do motorista de apoio definido top-level (Porto: Tiago Machado, Lisboa: Bruno).
    # Backward compat: ainda funciona com 'is_tiago: true' na viatura.
    support_driver_name = (config.get('support_driver') or {}).get('driver_name', '')

    vehicles = []
    for v in config['fleet']:
        if not v.get('active', True):
            continue
        is_support = v.get('is_tiago', False)
        if support_driver_name and v['driver'] == support_driver_name:
            is_support = True
        vehicles.append(Vehicle(
            plate=v['plate'],
            driver=v['driver'],
            active=True,
            max_volume_m3=v['max_volume_m3'],
            max_boxes=v['max_boxes'],
            home_city=v.get('home_city', ''),
            home_lat=v.get('home_lat', 0),
            home_lon=v.get('home_lon', 0),
            priority=v.get('priority', 99),
            is_tiago=is_support,
        ))
    vehicles.sort(key=lambda v: v.priority)
    return vehicles


def _match_transporter(transporter_text, vehicles):
    """
    Faz match do campo Transportador do input a uma viatura.
    Tenta por matricula e por nome do motorista.
    """
    if not transporter_text or not str(transporter_text).strip():
        return None
    text = str(transporter_text).strip().upper()
    if text in ('0', ''):
        return None

    for v in vehicles:
        if v.plate.upper().replace('-', '').replace(' ', '') == text.replace('-', '').replace(' ', ''):
            return v.plate
    for v in vehicles:
        if v.driver.upper() in text or text in v.driver.upper():
            return v.plate
    return None


def _estimate_route_km(stops, depot_lat, depot_lon, config):
    """Estimativa rapida de km totais de uma rota (nearest neighbor)."""
    if not stops:
        return 0
    rf = config.get('road_factor', 1.35)
    total_km = 0
    remaining = list(stops)
    cur_lat, cur_lon = depot_lat, depot_lon

    while remaining:
        best_i = 0
        best_dist = float('inf')
        for i, s in enumerate(remaining):
            d = estimate_distance_km(cur_lat, cur_lon, s.lat, s.lon, rf)
            if d < best_dist:
                best_dist = d
                best_i = i
        stop = remaining.pop(best_i)
        total_km += best_dist
        cur_lat, cur_lon = stop.lat, stop.lon

    total_km += estimate_distance_km(cur_lat, cur_lon, depot_lat, depot_lon, rf)
    return total_km


def _find_best_vehicle_for_zone(zone_name, zstops, assignments, vehicles,
                                dist_map, restrictions, max_zones, config):
    """
    Encontra a melhor viatura para uma zona inteira.
    Prioriza: motorista preferencial > proximidade geografica > restricoes.
    """
    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']
    rf = config.get('road_factor', 1.35)

    zc = dist_map.get(zone_name, {})
    preferred = zc.get('preferred_drivers', [])

    z_lat = sum(s.lat for s in zstops) / len(zstops)
    z_lon = sum(s.lon for s in zstops) / len(zstops)

    best_plate = None
    best_score = float('inf')

    for v in vehicles:
        current_zones = set(s.zone_name for s in assignments[v.plate])

        # Hard: max zonas por viatura
        if zone_name not in current_zones and len(current_zones) >= max_zones:
            continue

        # Hard: capacidade (com 10% tolerancia)
        current_boxes = sum(s.total_boxes for s in assignments[v.plate])
        zone_boxes = sum(s.total_boxes for s in zstops)
        if current_boxes + zone_boxes > v.max_boxes * 1.1:
            continue

        score = 0.0

        # Preferencia do motorista para esta zona (peso forte)
        if v.driver in preferred:
            idx = preferred.index(v.driver)
            score += idx * 25
        else:
            score += 120

        # Bonus se ja tem paragens nesta zona (manter zona junta)
        if zone_name in current_zones:
            score -= 60

        # Penalidade de restricao (soft)
        driver_restr = restrictions.get(v.driver, {})
        if zone_name in driver_restr.get('avoid_zones', []):
            score += 200

        # Proximidade geografica
        if assignments[v.plate]:
            v_lat = sum(s.lat for s in assignments[v.plate]) / len(assignments[v.plate])
            v_lon = sum(s.lon for s in assignments[v.plate]) / len(assignments[v.plate])
            dist = haversine_km(v_lat, v_lon, z_lat, z_lon)
            score += dist * 2
        else:
            dist = haversine_km(depot_lat, depot_lon, z_lat, z_lon)
            score += dist * 0.5

        if score < best_score:
            best_score = score
            best_plate = v.plate

    if not best_plate:
        return min(vehicles, key=lambda v: sum(s.total_boxes for s in assignments[v.plate])).plate
    return best_plate


def assign_stops_to_vehicles(stops, vehicles, config, weekday):
    """
    Atribui paragens a viaturas com base nas regras de negocio.

    Prioridades (documento de instrucoes definitivo):
    1. Janelas horarias (tratadas no sequenciamento OR-Tools)
    2. Transportador pre-atribuido no input
    3. Evitar ativar viatura extra (Tiago)
    4. Minimizar km totais da empresa
    5. Capacidade das viaturas
    6. Motorista preferencial por zona
    7. Equilibrio de carga
    8. Custo de combustivel

    Regras:
    - Maximo 3 zonas por viatura (max_routes_per_vehicle)
    - Manter zonas inteiras num so motorista (nao dividir)
    - Restricoes soft: Luis Martins evita Porto, Rui evita Cais de Gaia
    - Clientes do mesmo codigo postal juntos (ja agrupados em build_stops)
    """
    dist_map = config.get('distribution_map', {})
    restrictions = config.get('driver_restrictions', {})
    max_zones = config.get('max_routes_per_vehicle', 3)
    is_reduced = weekday in config['work_hours'].get('reduced_days', [])
    max_hours = config['work_hours']['reduced']['max_hours'] if is_reduced else config['work_hours']['normal']['max_hours']

    non_tiago = [v for v in vehicles if not v.is_tiago]
    tiago = next((v for v in vehicles if v.is_tiago), None)

    assignments = {v.plate: [] for v in non_tiago}

    # ── 1. Paragens pre-atribuidas (campo Transportador do input) ──
    unassigned = []
    for stop in stops:
        plate = _match_transporter(stop.pre_assigned_plate, non_tiago)
        if plate:
            assignments[plate].append(stop)
        else:
            unassigned.append(stop)

    # ── 2. Agrupar restantes por zona ──
    zone_stops = defaultdict(list)
    for stop in unassigned:
        zone_stops[stop.zone_name].append(stop)

    # ── 3. Atribuir zonas inteiras ao motorista preferencial ──
    # Zonas maiores primeiro (mais dificeis de colocar depois)
    zone_names = sorted(zone_stops.keys(), key=lambda z: -len(zone_stops[z]))

    for zone_name in zone_names:
        zstops = zone_stops[zone_name]
        best_plate = _find_best_vehicle_for_zone(
            zone_name, zstops, assignments, non_tiago,
            dist_map, restrictions, max_zones, config
        )
        assignments[best_plate].extend(zstops)

    # ── 4. Reequilibrar: respeitar max_hours + minimizar km totais ──
    _rebalance_for_efficiency(assignments, non_tiago, config, max_hours,
                              restrictions)

    # ── 5. Verificar se Tiago precisa sair ──
    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']

    tiago_needed = False
    if tiago:
        for plate, assigned in assignments.items():
            if not assigned:
                continue
            est_hours = _estimate_route_hours(assigned, depot_lat, depot_lon, config)
            if est_hours > max_hours:
                tiago_needed = True
                break

    tiago_in_distribution = False
    tiago_supports_plate = None

    if tiago_needed and tiago:
        tiago_in_distribution = True
        assignments[tiago.plate] = []
        _redistribute_with_tiago(assignments, non_tiago, tiago, config, max_hours)
    elif tiago:
        # Tiago nao sai — apoia o motorista mais carregado
        max_hours_plate = None
        max_h = 0
        for plate, assigned in assignments.items():
            if assigned:
                h = _estimate_route_hours(assigned, depot_lat, depot_lon, config)
                if h > max_h:
                    max_h = h
                    max_hours_plate = plate
        tiago_supports_plate = max_hours_plate

    return assignments, tiago_in_distribution, tiago_supports_plate


def _estimate_route_hours(stops, depot_lat, depot_lon, config):
    """Estimativa rapida de horas de rota (para decisoes de atribuicao)."""
    if not stops:
        return 0

    total_min = 0
    lc = config['loading']
    n = len(stops)
    load_min = lc['base_minutes'] + max(0, n - lc['base_clients']) * lc['extra_minutes_per_client']
    total_min += load_min

    rf = config.get('road_factor', 1.35)

    wh = config['work_hours']['normal']
    start_h, start_m = map(int, wh['start'].split(':'))
    start_minutes = start_h * 60 + start_m
    current_clock = start_minutes + load_min

    # Nearest neighbor ordering for estimation
    remaining = list(stops)
    cur_lat, cur_lon = depot_lat, depot_lon

    while remaining:
        best_i = 0
        best_dist = float('inf')
        for i, s in enumerate(remaining):
            d = estimate_distance_km(cur_lat, cur_lon, s.lat, s.lon, rf)
            if d < best_dist:
                best_dist = d
                best_i = i
        stop = remaining.pop(best_i)
        travel = estimate_travel_minutes(best_dist, cur_lat, cur_lon, stop.lat, stop.lon, config)
        # Fator de transito automatico (por hora e distancia)
        traffic_mult = _get_traffic_multiplier(
            current_clock, cur_lat, cur_lon, stop.lat, stop.lon, config)
        travel *= traffic_mult
        arrival = current_clock + travel
        # Wait for time window
        if stop.time_window_start and arrival < stop.time_window_start:
            arrival = stop.time_window_start
        total_min += (arrival - current_clock) + stop.unload_minutes
        current_clock = arrival + stop.unload_minutes
        cur_lat, cur_lon = stop.lat, stop.lon

    # Return trip to depot
    d = estimate_distance_km(cur_lat, cur_lon, depot_lat, depot_lon, rf)
    travel = estimate_travel_minutes(d, cur_lat, cur_lon, depot_lat, depot_lon, config)
    traffic_mult = _get_traffic_multiplier(
        current_clock, cur_lat, cur_lon, depot_lat, depot_lon, config)
    travel *= traffic_mult
    total_min += travel

    return total_min / 60


def _rebalance_for_efficiency(assignments, vehicles, config, max_hours,
                              restrictions=None):
    """
    Reequilibra para minimizar km totais da empresa e respeitar max_hours.

    Fase 1: Resolver viaturas acima de max_hours (mover outliers geograficos)
    Fase 2: Mover stops que estao mais perto de outra viatura (reduz km totais)
    """
    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']
    v_map = {v.plate: v for v in vehicles}
    if restrictions is None:
        restrictions = config.get('driver_restrictions', {})

    for iteration in range(15):
        moved = False

        # Calcular horas de todas as viaturas
        hours = {}
        for plate, stops in assignments.items():
            hours[plate] = _estimate_route_hours(
                stops, depot_lat, depot_lon, config) if stops else 0

        # ── Fase 1: Corrigir viaturas sobrecarregadas ──
        overloaded = [(p, h) for p, h in hours.items()
                      if h > max_hours and len(assignments[p]) > 1]
        overloaded.sort(key=lambda x: -x[1])

        for plate, h in overloaded:
            stops = assignments[plate]
            if len(stops) <= 1:
                continue

            # Centroide desta viatura
            v_lat = sum(s.lat for s in stops) / len(stops)
            v_lon = sum(s.lon for s in stops) / len(stops)

            # Stops ordenados por distancia ao centroide (outliers primeiro)
            stops_by_outlier = sorted(stops,
                key=lambda s: -haversine_km(s.lat, s.lon, v_lat, v_lon))

            for move_stop in stops_by_outlier:
                best_plate = None
                best_dist = float('inf')

                for p2 in assignments:
                    if p2 == plate:
                        continue
                    v2 = v_map.get(p2)
                    if not v2:
                        continue
                    new_boxes = sum(s.total_boxes for s in assignments[p2]) + move_stop.total_boxes
                    if new_boxes > v2.max_boxes:
                        continue

                    # Verificar restricoes do motorista destino
                    d_restr = restrictions.get(v2.driver, {})
                    avoid_cities = [c.upper() for c in d_restr.get('avoid_cities', [])]
                    if move_stop.city and move_stop.city.upper().strip() in avoid_cities:
                        continue

                    # Distancia do stop ao centroide da viatura destino
                    if assignments[p2]:
                        t_lat = sum(s.lat for s in assignments[p2]) / len(assignments[p2])
                        t_lon = sum(s.lon for s in assignments[p2]) / len(assignments[p2])
                    else:
                        t_lat, t_lon = depot_lat, depot_lon
                    dist_to_target = haversine_km(move_stop.lat, move_stop.lon, t_lat, t_lon)

                    # Nao sobrecarregar o destino
                    h_target = _estimate_route_hours(
                        assignments[p2] + [move_stop], depot_lat, depot_lon, config)
                    if h_target > max_hours and hours.get(p2, 0) <= max_hours:
                        continue

                    if dist_to_target < best_dist:
                        best_dist = dist_to_target
                        best_plate = p2

                if best_plate:
                    assignments[plate].remove(move_stop)
                    assignments[best_plate].append(move_stop)
                    moved = True
                    break

            if moved:
                break

        if moved:
            continue

        # ── Fase 2: Otimizar km — mover stops que ficam melhor noutro veiculo ──
        for plate in list(assignments.keys()):
            stops = assignments[plate]
            if len(stops) <= 2:
                continue

            v_lat = sum(s.lat for s in stops) / len(stops)
            v_lon = sum(s.lon for s in stops) / len(stops)

            for move_stop in stops:
                dist_to_own = haversine_km(move_stop.lat, move_stop.lon, v_lat, v_lon)

                best_target = None
                best_ratio = 1.0  # So move se distancia ao target < 50% da distancia actual

                for p2 in assignments:
                    if p2 == plate or not assignments[p2]:
                        continue
                    v2 = v_map.get(p2)
                    if not v2:
                        continue
                    new_boxes = sum(s.total_boxes for s in assignments[p2]) + move_stop.total_boxes
                    if new_boxes > v2.max_boxes:
                        continue

                    # Restricoes do motorista destino
                    d_restr = restrictions.get(v2.driver, {})
                    avoid_cities = [c.upper() for c in d_restr.get('avoid_cities', [])]
                    if move_stop.city and move_stop.city.upper().strip() in avoid_cities:
                        continue

                    t_lat = sum(s.lat for s in assignments[p2]) / len(assignments[p2])
                    t_lon = sum(s.lon for s in assignments[p2]) / len(assignments[p2])
                    dist_to_target = haversine_km(move_stop.lat, move_stop.lon, t_lat, t_lon)

                    # So mover se fica significativamente mais perto (>50% melhoria)
                    if dist_to_own > 0.5 and dist_to_target < dist_to_own * 0.5:
                        h_target = _estimate_route_hours(
                            assignments[p2] + [move_stop], depot_lat, depot_lon, config)
                        if h_target <= max_hours:
                            ratio = dist_to_target / max(dist_to_own, 0.1)
                            if ratio < best_ratio:
                                best_ratio = ratio
                                best_target = p2

                if best_target:
                    assignments[plate].remove(move_stop)
                    assignments[best_target].append(move_stop)
                    moved = True
                    break

            if moved:
                break

        if not moved:
            break


def _redistribute_with_tiago(assignments, non_tiago, tiago, config, max_hours):
    """
    Redistribui stops incluindo Tiago para respeitar max_hours.
    Tiago recebe paragens do motorista mais sobrecarregado,
    minimizando km totais da empresa.
    """
    all_stops = []
    for plate, stops in assignments.items():
        all_stops.extend(stops)
    all_vehicles = non_tiago + [tiago]

    # Limpar tudo e reatribuir
    for v in all_vehicles:
        assignments[v.plate] = []

    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']
    dist_map = config.get('distribution_map', {})
    restrictions = config.get('driver_restrictions', {})
    max_zones = config.get('max_routes_per_vehicle', 3)

    # Reagrupar por zona
    zone_stops = defaultdict(list)
    for stop in all_stops:
        zone_stops[stop.zone_name].append(stop)

    # Atribuir zonas inteiras ao motorista preferencial (incluindo Tiago)
    zone_names = sorted(zone_stops.keys(), key=lambda z: -len(zone_stops[z]))

    for zone_name in zone_names:
        zstops = zone_stops[zone_name]
        best_plate = _find_best_vehicle_for_zone(
            zone_name, zstops, assignments, all_vehicles,
            dist_map, restrictions, max_zones, config
        )
        assignments[best_plate].extend(zstops)

    # Reequilibrar incluindo Tiago
    _rebalance_for_efficiency(assignments, all_vehicles, config, max_hours,
                              restrictions)


def sequence_stops(stops, depot_lat, depot_lon, home_lat, home_lon, config, weekday=None):
    """
    Usa OR-Tools para encontrar a melhor ordem de visita.
    Resolve um TSP com janelas horarias REAIS integradas no solver.
    Usa OSRM Table API para a matriz de distancias/tempos reais.
    """
    if len(stops) == 0:
        return []
    if len(stops) == 1:
        return [0]

    n = len(stops) + 1  # +1 para o deposito
    rf = config.get('road_factor', 1.35)

    all_points = [(depot_lat, depot_lon)] + [(s.lat, s.lon) for s in stops]

    # Tentar OSRM Table API (uma chamada para toda a matriz)
    osrm_result = None
    if _check_osrm():
        osrm_result = osrm_table(all_points)

    if osrm_result:
        dist_km_matrix, time_min_matrix = osrm_result
        dist_matrix = [[int(dist_km_matrix[i][j] * 1000) for j in range(n)] for i in range(n)]
        time_matrix = [[int(time_min_matrix[i][j]) for j in range(n)] for i in range(n)]
    else:
        dist_matrix = [[0] * n for _ in range(n)]
        time_matrix = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                d = estimate_distance_km(
                    all_points[i][0], all_points[i][1],
                    all_points[j][0], all_points[j][1], rf
                )
                t = estimate_travel_minutes(
                    d,
                    all_points[i][0], all_points[i][1],
                    all_points[j][0], all_points[j][1],
                    config
                )
                dist_matrix[i][j] = int(d * 1000)
                time_matrix[i][j] = int(t)

    # Adicionar tempo de descarga ao tempo de viagem
    for j in range(1, n):
        service_time = int(stops[j-1].unload_minutes)
        for i in range(n):
            time_matrix[i][j] += service_time

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return time_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Calcular hora de saida do armazem (para converter janelas absolutas em relativas)
    is_reduced = False
    if weekday is not None:
        is_reduced = weekday in config['work_hours'].get('reduced_days', [])
    wh = config['work_hours']['reduced'] if is_reduced else config['work_hours']['normal']
    start_h, start_m = map(int, wh['start'].split(':'))
    start_minutes = start_h * 60 + start_m
    lc = config['loading']
    load_min = lc['base_minutes'] + max(0, len(stops) - lc['base_clients']) * lc['extra_minutes_per_client']
    departure_minutes = start_minutes + load_min

    # Dimensao de tempo com janelas horarias reais
    routing.AddDimension(
        transit_callback_index,
        180,   # max espera (3 horas — para janelas tipo "a partir das 10h")
        900,   # max tempo total (15 horas)
        True,  # Force start cumul to zero (tempo comeca em 0 na saida do armazem)
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')

    # Janelas horarias reais convertidas para minutos relativos a saida do armazem
    for i in range(1, n):
        stop = stops[i-1]
        idx = manager.NodeToIndex(i)

        tw_start_rel = 0
        tw_end_rel = 900

        if stop.time_window_start is not None:
            tw_start_rel = max(0, stop.time_window_start - departure_minutes)
        if stop.time_window_end is not None:
            tw_end_rel = max(0, stop.time_window_end - departure_minutes)
            # Dar margem de 30 min para o solver encontrar solucao
            # (melhor chegar um pouco atrasado do que nao ter solucao)
            tw_end_rel += 30

        time_dimension.CumulVar(idx).SetRange(tw_start_rel, tw_end_rel)

    # Deposito: janela [0, 0] — saida imediata
    depot_idx = manager.NodeToIndex(0)
    time_dimension.CumulVar(depot_idx).SetRange(0, 0)

    # Penalizar atrasos em janelas horarias (soft constraint)
    for i in range(1, n):
        stop = stops[i-1]
        if stop.time_window_end is not None:
            idx = manager.NodeToIndex(i)
            tw_end_rel = max(0, stop.time_window_end - departure_minutes)
            # Custo extra por cada minuto de atraso apos a janela
            time_dimension.SetCumulVarSoftUpperBound(idx, tw_end_rel, 50)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.FromSeconds(5)

    solution = routing.SolveWithParameters(search_parameters)

    if solution:
        order = []
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node > 0:
                order.append(node - 1)
            index = solution.Value(routing.NextVar(index))
        return order
    else:
        # Se nao encontrar solucao com janelas, tentar sem (so minimizar tempo)
        # Isto acontece se as janelas sao impossiveis de cumprir
        routing2 = pywrapcp.RoutingModel(manager)
        transit_cb2 = routing2.RegisterTransitCallback(time_callback)
        routing2.SetArcCostEvaluatorOfAllVehicles(transit_cb2)
        solution2 = routing2.SolveWithParameters(search_parameters)
        if solution2:
            order = []
            index = routing2.Start(0)
            while not routing2.IsEnd(index):
                node = manager.IndexToNode(index)
                if node > 0:
                    order.append(node - 1)
                index = solution2.Value(routing2.NextVar(index))
            return order
        return list(range(len(stops)))



def calculate_route_times(ordered_stops, vehicle, config, weekday,
                          tiago_supports=False):
    """
    Calcula tempos detalhados para uma rota ja sequenciada.
    Devolve um RoutePlan completo.
    """
    is_reduced = weekday in config['work_hours'].get('reduced_days', [])
    wh = config['work_hours']['reduced'] if is_reduced else config['work_hours']['normal']

    start_h, start_m = map(int, wh['start'].split(':'))
    start_minutes = start_h * 60 + start_m

    # Tempo de carga
    lc = config['loading']
    n_clients = len(ordered_stops)
    load_minutes = lc['base_minutes'] + max(0, n_clients - lc['base_clients']) * lc['extra_minutes_per_client']
    departure_minutes = start_minutes + load_minutes

    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']
    rf = config.get('road_factor', 1.35)
    # Ajuste de tempo de descarga em cidade especial
    # Porto: -0.10 (reduz 10%), Lisboa: +0.05 (aumenta 5%)
    # Backward compat com 'porto_time_reduction' (era positivo = redução)
    if 'city_time_adjustment' in config:
        city_adj = config['city_time_adjustment']
    else:
        city_adj = -config.get('porto_time_reduction', 0.10)

    # Tolerância de imponderáveis aplicada a cada deslocação (Lisboa: +5%)
    unforeseen_tol = config.get('unforeseen_tolerance', 0.0)

    # Redução adicional quando viatura de apoio ajuda
    support_red = config.get('support_driver_reduction',
                             config.get('tiago_support_reduction', 0.10))

    # Ajuste individual do motorista (% extra ou menos no tempo total)
    driver_adj = 0.0
    for v in config.get('fleet', []):
        if v['plate'] == vehicle.plate:
            driver_adj = v.get('driver_adjustment', 0.0)
            break

    assigned_stops = []
    current_time = departure_minutes
    current_lat, current_lon = depot_lat, depot_lon
    total_km = 0.0
    total_boxes = 0
    total_volume = 0.0
    zones = set()

    for i, stop in enumerate(ordered_stops):
        dist = estimate_distance_km(current_lat, current_lon, stop.lat, stop.lon, rf)
        travel = estimate_travel_minutes(dist, current_lat, current_lon, stop.lat, stop.lon, config)
        # Aplicar fator de transito automatico (por hora e tipo de trajeto)
        traffic_mult = _get_traffic_multiplier(
            current_time, current_lat, current_lon, stop.lat, stop.lon, config)
        travel *= traffic_mult
        # Aplicar ajuste individual do motorista
        travel *= (1 + driver_adj)
        # Tolerancia de imponderaveis (Lisboa: +5%)
        travel *= (1 + unforeseen_tol)
        total_km += dist

        arrival_time = current_time + travel

        # Se existe janela e chegamos antes, esperamos
        if stop.time_window_start and arrival_time < stop.time_window_start:
            arrival_time = stop.time_window_start

        # Tempo de descarga com ajustes
        unload = stop.unload_minutes
        # Cidade especial: signed adjustment (Porto: -0.10, Lisboa: +0.05)
        if stop.is_porto:
            unload *= (1 + city_adj)
        # Viatura de apoio: redução adicional
        if tiago_supports:
            unload *= (1 - support_red)
        # Aplicar ajuste individual do motorista a descarga
        unload *= (1 + driver_adj)

        arrival_h = int(arrival_time) // 60
        arrival_m = int(arrival_time) % 60

        assigned = AssignedStop(
            stop=stop,
            delivery_order=i + 1,
            total_stops=n_clients,
            estimated_arrival=f"{arrival_h:02d}:{arrival_m:02d}",
            arrival_minutes=int(arrival_time),
        )
        assigned_stops.append(assigned)

        current_time = arrival_time + unload
        current_lat, current_lon = stop.lat, stop.lon
        total_boxes += stop.total_boxes
        total_volume += stop.total_volume
        zones.add(stop.zone_name)

    # Viagem ate casa do motorista
    last_departure = current_time
    home_dist = estimate_distance_km(current_lat, current_lon,
                                      vehicle.home_lat, vehicle.home_lon, rf)
    home_travel = estimate_travel_minutes(home_dist, current_lat, current_lon,
                                           vehicle.home_lat, vehicle.home_lon, config)
    traffic_mult = _get_traffic_multiplier(
        last_departure, current_lat, current_lon, vehicle.home_lat, vehicle.home_lon, config)
    home_travel *= traffic_mult
    home_travel *= (1 + driver_adj)
    home_travel *= (1 + unforeseen_tol)
    total_km += home_dist
    arrival_home = last_departure + home_travel
    total_hours = (arrival_home - start_minutes) / 60

    def fmt(mins):
        return f"{int(mins)//60:02d}:{int(mins)%60:02d}"

    fuel_cost = (total_km / 100) * config['fuel']['consumption_per_100km'] * config['fuel']['price_per_liter']

    plan = RoutePlan(
        vehicle=vehicle,
        stops=assigned_stops,
        zones=sorted(zones),
        departure_time=fmt(departure_minutes),
        last_client_departure=fmt(last_departure),
        arrival_home=fmt(arrival_home),
        total_hours=round(total_hours, 2),
        total_km=round(total_km, 1),
        fuel_cost=round(fuel_cost, 2),
        total_boxes=total_boxes,
        total_clients=n_clients,
        volume_pct=round(total_volume / vehicle.max_volume_m3, 4) if vehicle.max_volume_m3 > 0 else 0,
        tiago_supports=tiago_supports,
    )
    return plan


def route(lines, config, expedition_date):
    """
    Funcao principal: recebe linhas de picking e config,
    devolve lista de RoutePlan.
    """
    weekday = expedition_date.weekday()
    day_names = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
    print(f"  Data: {expedition_date.strftime('%d/%m/%Y')} ({day_names[weekday]})")

    # 0. Verificar OSRM
    if _check_osrm():
        print(f"  🛰️ OSRM: disponivel — a usar distancias reais pela estrada")
    else:
        print(f"  ⚠️ OSRM: indisponivel — a usar haversine × road_factor como fallback")

    # 1. Construir paragens (inclui geocodificacao via Nominatim)
    from .geo import _nominatim_cache
    cache_before = len(_nominatim_cache)
    stops = build_stops(lines, config)
    new_geocodes = len(_nominatim_cache) - cache_before
    print(f"  Paragens: {len(stops)} (de {len(lines)} linhas de picking)")
    if new_geocodes > 0:
        print(f"  📍 Geocodificacao: {new_geocodes} codigos postais resolvidos via Nominatim")

    # 2. Construir frota
    vehicles = build_vehicles(config)
    print(f"  Viaturas ativas: {len(vehicles)}")

    # 3. Atribuir paragens a viaturas
    assignments, tiago_in_dist, tiago_supports_plate = assign_stops_to_vehicles(
        stops, vehicles, config, weekday
    )

    if tiago_in_dist:
        print(f"  Tiago: SAI em distribuicao")
    else:
        if tiago_supports_plate:
            v = next((v for v in vehicles if v.plate == tiago_supports_plate), None)
            print(f"  Tiago: APOIO ao {v.driver if v else tiago_supports_plate}")
        else:
            print(f"  Tiago: sem atividade")

    # 4. Sequenciar e calcular tempos para cada viatura
    depot_lat = config['depot']['lat']
    depot_lon = config['depot']['lon']
    route_plans = []

    for vehicle in vehicles:
        v_stops = assignments.get(vehicle.plate, [])
        if not v_stops and not vehicle.is_tiago:
            continue
        if not v_stops:
            continue

        # Sequenciar com OR-Tools (janelas horarias integradas no solver)
        order = sequence_stops(
            v_stops, depot_lat, depot_lon,
            vehicle.home_lat, vehicle.home_lon, config, weekday
        )
        ordered = [v_stops[i] for i in order]

        # Calcular tempos
        is_supported = (not tiago_in_dist and tiago_supports_plate == vehicle.plate)
        plan = calculate_route_times(ordered, vehicle, config, weekday, is_supported)
        route_plans.append(plan)

        print(f"  {vehicle.plate} ({vehicle.driver}): {plan.total_clients} clientes, "
              f"{plan.total_boxes} cx, {plan.total_hours:.1f}h, {plan.total_km:.0f}km")

    return route_plans


