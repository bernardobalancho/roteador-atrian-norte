"""
Geocodificacao por codigo postal e calculo de distancias.

Usa Nominatim (OpenStreetMap) para geocodificacao precisa por codigo postal.
Usa OSRM (Open Source Routing Machine) para distancias e tempos REAIS
pela estrada, com fallback para haversine se a API nao estiver disponivel.

Ambos gratuitos e baseados em dados OpenStreetMap.
"""
import math
import requests
import time as _time
from functools import lru_cache

# ── Nominatim Config (geocodificacao) ──
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
NOMINATIM_HEADERS = {
    'User-Agent': 'AtrianNorteRouter/1.0 (delivery routing tool)',
    'Accept-Language': 'pt',
}
_nominatim_cache = {}       # {postal_code: (lat, lon)}
_last_nominatim_call = 0.0  # rate limiting: 1 req/sec

# ── OSRM Config ──
OSRM_BASE = "https://router.project-osrm.org"
OSRM_TIMEOUT = 10  # segundos por request
OSRM_MAX_TABLE_SIZE = 80  # max pontos por pedido table
_osrm_available = None  # None = nao testado, True/False

# Cache para evitar repetir pedidos (pares de pontos)
_route_cache = {}


def _check_osrm():
    """Testa se o servidor OSRM esta acessivel."""
    global _osrm_available
    if _osrm_available is not None:
        return _osrm_available
    try:
        # Teste rapido: rota curta no Porto
        r = requests.get(
            f"{OSRM_BASE}/route/v1/driving/-8.61,41.15;-8.62,41.16",
            params={"overview": "false"},
            timeout=5
        )
        _osrm_available = (r.status_code == 200 and r.json().get("code") == "Ok")
    except Exception:
        _osrm_available = False
    return _osrm_available


def osrm_route(lat1, lon1, lat2, lon2):
    """
    Obtem distancia (km) e duracao (minutos) reais pela estrada via OSRM.

    Retorna (distance_km, duration_minutes) ou None se falhar.
    OSRM usa coordenadas na ordem lon,lat (nao lat,lon!).
    """
    # Cache key com 4 decimais (precisao ~11m)
    key = (round(lat1, 4), round(lon1, 4), round(lat2, 4), round(lon2, 4))
    if key in _route_cache:
        return _route_cache[key]

    # Mesma localizacao
    if key[0] == key[2] and key[1] == key[3]:
        _route_cache[key] = (0.0, 0.0)
        return (0.0, 0.0)

    try:
        url = f"{OSRM_BASE}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
        r = requests.get(url, params={"overview": "false"}, timeout=OSRM_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                dist_km = route["distance"] / 1000.0  # metros → km
                dur_min = route["duration"] / 60.0     # segundos → minutos
                result = (dist_km, dur_min)
                _route_cache[key] = result
                return result
    except Exception:
        pass

    return None


def osrm_table(points):
    """
    Obtem matriz de distancias e duracoes para N pontos via OSRM Table API.

    Args:
        points: lista de (lat, lon) — primeiro ponto e tipicamente o deposito

    Retorna (dist_matrix_km, time_matrix_min) ou None se falhar.
    dist_matrix[i][j] = distancia em km de i para j
    time_matrix[i][j] = duracao em minutos de i para j
    """
    if not points or len(points) < 2:
        return None

    if len(points) > OSRM_MAX_TABLE_SIZE:
        return None

    # Construir string de coordenadas: lon,lat;lon,lat;...
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    url = f"{OSRM_BASE}/table/v1/driving/{coords}"

    try:
        r = requests.get(
            url,
            params={"annotations": "distance,duration"},
            timeout=OSRM_TIMEOUT * 2  # table pode demorar mais
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "Ok":
                durations = data["durations"]  # segundos
                distances = data["distances"]  # metros

                n = len(points)
                dist_km = [[0.0] * n for _ in range(n)]
                time_min = [[0.0] * n for _ in range(n)]

                for i in range(n):
                    for j in range(n):
                        d = distances[i][j]
                        t = durations[i][j]
                        dist_km[i][j] = (d / 1000.0) if d is not None else 0.0
                        time_min[i][j] = (t / 60.0) if t is not None else 0.0

                return dist_km, time_min
    except Exception:
        pass

    return None


def clear_cache():
    """Limpa o cache de rotas (chamar entre dias diferentes se necessario)."""
    global _route_cache, _osrm_available
    _route_cache.clear()
    _osrm_available = None


# ── Coordenadas aproximadas por codigo postal ──
POSTAL_COORDS = {
    # Porto centro
    "4000": (41.1496, -8.6109),
    "4049": (41.1496, -8.6109),
    "4050": (41.1410, -8.6150),
    # Porto Foz / Boavista
    "4100": (41.1620, -8.6680),
    "4150": (41.1560, -8.6500),
    # Porto Paranhos / Campanha
    "4200": (41.1700, -8.5900),
    "4250": (41.1750, -8.6400),
    # Vila Nova de Gaia
    "4400": (41.1240, -8.6120),
    "4405": (41.0900, -8.6350),
    "4410": (41.1050, -8.5700),
    "4420": (41.1500, -8.5350),  # Gondomar / Valbom
    "4430": (41.1150, -8.6200),
    "4435": (41.1000, -8.5600),  # Rio Tinto
    # Matosinhos / Leca
    "4450": (41.1900, -8.7000),
    "4455": (41.2150, -8.7200),  # Perafita
    "4460": (41.2000, -8.6800),  # Sra Hora
    # Maia
    "4470": (41.2350, -8.6200),
    "4475": (41.2500, -8.6100),
    # Povoa de Varzim
    "4490": (41.3833, -8.7667),
    # Espinho
    "4500": (41.0076, -8.6410),
    "4505": (40.9900, -8.6300),
    # Vila do Conde
    "4480": (41.3517, -8.7431),
    # Lordelo / Paredes
    "4580": (41.2000, -8.3300),
    "4585": (41.1700, -8.3100),
    # Pacos de Ferreira
    "4590": (41.2800, -8.3900),
    # Santo Tirso / Burgaes
    "4780": (41.3440, -8.4770),
    "4785": (41.3200, -8.5000),
    # Braga
    "4700": (41.5503, -8.4200),
    "4705": (41.5700, -8.3900),
    "4710": (41.5600, -8.3800),
    "4715": (41.5500, -8.4500),
    # Barcelos
    "4750": (41.5321, -8.6174),
    "4755": (41.5400, -8.6000),
    # Vila Verde
    "4730": (41.6450, -8.4400),
    # Guimaraes
    "4800": (41.4428, -8.2919),
    "4810": (41.4500, -8.3100),
    # Famalicao
    "4760": (41.4080, -8.5186),
    "4765": (41.4200, -8.5000),
    # Esposende
    "4740": (41.5350, -8.7800),
    # Viana do Castelo
    "4900": (41.6935, -8.8327),
    "4905": (41.7000, -8.8200),
    # Ponte de Lima
    "4990": (41.7680, -8.5840),
    # Aveiro
    "3800": (40.6405, -8.6538),
    "3810": (40.6405, -8.6538),
    "3830": (40.6200, -8.5000),  # Ilhavo
    # Albergaria-a-Velha
    "3850": (40.6900, -8.4800),
    # Estarreja
    "3860": (40.7520, -8.5700),
    # Ovar
    "3880": (40.8592, -8.6262),
    "3885": (40.9200, -8.5800),  # Cortegaca
    # Santa Maria da Feira
    "4520": (40.9256, -8.5426),
    # Sao Joao da Madeira
    "3700": (40.9005, -8.4907),
    # Modivas - Vila do Conde (deposito)
    "4485": (41.3158, -8.7292),
    # Penafiel
    "4560": (41.2078, -8.2843),
    # Baiao
    "4640": (41.1614, -8.0345),
    # Freixo / Fornelos Ponte de Lima
    "4990": (41.7680, -8.5840),
}


def _format_postal(postal_code):
    """Formata codigo postal para 4XXX-XXX."""
    clean = str(postal_code).replace(' ', '').replace('-', '').strip()
    if not clean or clean == '0':
        return None
    if len(clean) >= 7:
        return f"{clean[:4]}-{clean[4:7]}"
    elif len(clean) >= 4:
        return f"{clean[:4]}-{clean[4:].ljust(3, '0')}"
    return None


def _nominatim_rate_limit():
    """Garante intervalo minimo de 1 segundo entre pedidos Nominatim."""
    global _last_nominatim_call
    now = _time.time()
    elapsed = now - _last_nominatim_call
    if elapsed < 1.05:
        _time.sleep(1.05 - elapsed)
    _last_nominatim_call = _time.time()


def _nominatim_search(params):
    """Faz um pedido ao Nominatim com rate limiting."""
    _nominatim_rate_limit()
    try:
        r = requests.get(
            f"{NOMINATIM_BASE}/search", params=params,
            headers=NOMINATIM_HEADERS, timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                return (float(data[0]['lat']), float(data[0]['lon']))
    except Exception:
        pass
    return None


def _get_expected_coords(postal_code):
    """Obtem coordenadas esperadas do dicionario estatico (para validacao)."""
    clean = str(postal_code).replace('-', '').replace(' ', '')
    if len(clean) < 4:
        return None
    prefix4 = clean[:4]
    if prefix4 in POSTAL_COORDS:
        return POSTAL_COORDS[prefix4]
    prefix3 = clean[:3]
    for key, coords in POSTAL_COORDS.items():
        if key[:3] == prefix3:
            return coords
    return None


def _validate_result(result, expected, max_km=40):
    """Verifica se o resultado esta a uma distancia razoavel do esperado."""
    if not expected or not result:
        return result is not None
    dist = haversine_km(result[0], result[1], expected[0], expected[1])
    return dist < max_km


def geocode_postal(postal_code: str, city: str = None,
                   address: str = None) -> tuple:
    """
    Converte codigo postal + morada em (lat, lon).

    Estrategia (do mais preciso ao menos preciso):
    1. Pesquisa por morada completa + CP + cidade (precisao ~rua)
    2. Pesquisa por codigo postal + cidade (precisao ~bairro)
    3. Dicionario estatico por prefixo 4 digitos (precisao ~concelho)

    Resultados sao validados contra a zona esperada para evitar
    matches em cidades erradas.
    """
    if not postal_code:
        return (0.0, 0.0)

    pc = _format_postal(postal_code)
    if not pc:
        return (0.0, 0.0)

    # Cache key inclui morada para precisao maxima
    addr_clean = str(address or '').strip()[:60] if address else ''
    cache_key = f"{pc}|{addr_clean}" if addr_clean else pc

    if cache_key in _nominatim_cache:
        cached = _nominatim_cache[cache_key]
        if cached:
            return cached
        # cached is None = Nominatim nao encontrou, usar fallback

    expected = _get_expected_coords(postal_code)
    result = None

    # ── 1. Pesquisa por morada completa (mais precisa) ──
    if addr_clean and len(addr_clean) > 3:
        # So usar se parece uma morada (nao um numero/codigo)
        has_letters = any(c.isalpha() for c in addr_clean)
        if has_letters:
            city_str = str(city or '').strip()
            q = f"{addr_clean}, {pc}, {city_str}, Portugal" if city_str else f"{addr_clean}, {pc}, Portugal"
            result = _nominatim_search({
                'q': q, 'format': 'json', 'limit': 1, 'countrycodes': 'pt',
            })
            # Validar: esta na zona certa?
            if result and not _validate_result(result, expected, max_km=35):
                result = None  # Match errado, descartar

    # ── 2. Pesquisa por codigo postal + cidade ──
    if not result:
        city_str = str(city or '').strip()
        if city_str and city_str != '0':
            result = _nominatim_search({
                'postalcode': pc, 'city': city_str,
                'country': 'Portugal', 'format': 'json', 'limit': 1,
            })
            if result and not _validate_result(result, expected, max_km=40):
                result = None

    # ── 3. Pesquisa so por codigo postal ──
    if not result:
        result = _nominatim_search({
            'postalcode': pc, 'country': 'Portugal',
            'format': 'json', 'limit': 1,
        })
        if result and not _validate_result(result, expected, max_km=50):
            result = None

    # Guardar no cache (mesmo se None, para nao repetir)
    _nominatim_cache[cache_key] = result

    if result:
        return result

    # ── 4. Fallback: dicionario estatico ──
    if expected:
        return expected

    clean = str(postal_code).replace('-', '').replace(' ', '')
    prefix2 = clean[:2] if len(clean) >= 2 else ''
    for key, coords in POSTAL_COORDS.items():
        if key[:2] == prefix2:
            return coords

    return (41.15, -8.61)  # ultimo fallback: centro do Porto


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia em km entre dois pontos (formula de Haversine)."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def estimate_distance_km(lat1, lon1, lat2, lon2, road_factor=1.35):
    """
    Distancia estimada por estrada.
    Tenta OSRM primeiro; se falhar, usa haversine × road_factor.
    """
    if _check_osrm():
        result = osrm_route(lat1, lon1, lat2, lon2)
        if result:
            return result[0]  # distancia real em km
    return haversine_km(lat1, lon1, lat2, lon2) * road_factor


def estimate_travel_minutes(dist_km, lat1, lon1, lat2, lon2, config):
    """
    Tempo de viagem estimado em minutos.
    Tenta OSRM primeiro; se falhar, usa velocidades medias.
    """
    if dist_km < 0.5:
        return 2.0

    if _check_osrm():
        result = osrm_route(lat1, lon1, lat2, lon2)
        if result:
            return result[1]  # duracao real em minutos

    # Fallback: velocidades medias
    straight_km = haversine_km(lat1, lon1, lat2, lon2)
    if straight_km < 5:
        speed = config['speed']['urban']
    elif straight_km < 20:
        speed = config['speed']['suburban']
    else:
        speed = config['speed']['intercity']
    return (dist_km / speed) * 60
