"""
Geocodificacao por codigo postal e calculo de distancias.

Usa uma tabela de coordenadas aproximadas para os codigos postais
da zona Norte de Portugal. A distancia real e estimada como:
   haversine × road_factor

Mais tarde pode ser substituido por Google Maps, OSRM, etc.
"""
import math

# Coordenadas aproximadas por prefixo de codigo postal (4 digitos).
# Fonte: centroide aproximado de cada area postal.
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
    "4705": (41.5503, -8.4200),
    "4710": (41.5600, -8.3800),
    "4715": (41.5500, -8.4500),
    # Celeiros Braga
    "4705": (41.5700, -8.3900),
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


def geocode_postal(postal_code: str) -> tuple:
    """
    Converte codigo postal em (lat, lon).
    Tenta o prefixo de 4 digitos. Se nao encontrar, tenta 3 ou 2 digitos
    e devolve o mais proximo.
    """
    if not postal_code:
        return (0.0, 0.0)

    clean = str(postal_code).replace('-', '').replace(' ', '')
    if len(clean) < 4:
        clean = clean.ljust(4, '0')

    prefix4 = clean[:4]
    if prefix4 in POSTAL_COORDS:
        return POSTAL_COORDS[prefix4]

    prefix3 = clean[:3]
    best = None
    best_diff = 9999
    for key, coords in POSTAL_COORDS.items():
        if key[:3] == prefix3:
            diff = abs(int(key) - int(prefix4))
            if diff < best_diff:
                best_diff = diff
                best = coords

    if best:
        return best

    prefix2 = clean[:2]
    for key, coords in POSTAL_COORDS.items():
        if key[:2] == prefix2:
            return coords

    return (41.15, -8.61)  # fallback: centro do Porto


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia em km entre dois pontos (formula de Haversine)."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def estimate_distance_km(lat1, lon1, lat2, lon2, road_factor=1.35):
    """Distancia estimada por estrada (haversine × fator)."""
    return haversine_km(lat1, lon1, lat2, lon2) * road_factor


def estimate_travel_minutes(dist_km, lat1, lon1, lat2, lon2, config):
    """
    Tempo de viagem estimado em minutos.
    Usa velocidade urbana se ambos os pontos estao dentro da mesma area,
    intercidade se estao longe.
    """
    if dist_km < 0.5:
        return 2.0

    straight_km = haversine_km(lat1, lon1, lat2, lon2)

    if straight_km < 5:
        speed = config['speed']['urban']
    elif straight_km < 20:
        speed = config['speed']['suburban']
    else:
        speed = config['speed']['intercity']

    return (dist_km / speed) * 60
