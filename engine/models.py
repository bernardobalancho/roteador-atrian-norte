"""
Estruturas de dados do roteador.
Cada classe representa uma "coisa" do mundo real.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PickingLine:
    """Uma linha do mapa de picking (= um produto numa encomenda)."""
    row_index: int
    client_code: str
    client_name: str
    article_code: str
    article_desc: str
    quantity: int
    transporter: str
    expedition_date: str
    doc_final: str
    doc_origin: str
    delegation: str
    weight: float
    address1: str
    address2: str
    address3: str
    postal_code: str
    city: str
    obs_external: str
    shipping_address: str
    lot: str
    sale_unit: str
    expedition_address: str
    height: float
    width: float
    depth: float
    route_code: str


@dataclass
class Stop:
    """Uma paragem = um ponto de entrega (cliente + endereco de expedicao)."""
    stop_id: str
    client_code: str
    client_name: str
    shipping_address: str
    address1: str
    postal_code: str
    city: str
    route_code: str
    zone_name: str
    lat: float = 0.0
    lon: float = 0.0
    total_boxes: int = 0
    total_weight: float = 0.0
    total_volume: float = 0.0
    time_window_start: Optional[int] = None   # minutos desde 00:00
    time_window_end: Optional[int] = None     # minutos desde 00:00
    time_window_text: str = ""
    pre_assigned_plate: str = ""
    is_porto: bool = False
    lines: list = field(default_factory=list)  # lista de PickingLine
    unload_minutes: float = 0.0


@dataclass
class Vehicle:
    """Uma viatura da frota."""
    plate: str
    driver: str
    active: bool
    max_volume_m3: float
    max_boxes: int
    home_city: str
    home_lat: float
    home_lon: float
    priority: int
    is_tiago: bool = False


@dataclass
class AssignedStop:
    """Uma paragem ja atribuida a uma viatura, com ordem e hora."""
    stop: Stop
    delivery_order: int       # 1, 2, 3...
    total_stops: int          # total de paragens nesta viatura
    estimated_arrival: str    # "HH:MM"
    arrival_minutes: int      # minutos desde 00:00


@dataclass
class RoutePlan:
    """O plano completo de uma viatura."""
    vehicle: Vehicle
    stops: list               # lista de AssignedStop
    zones: list               # nomes das zonas
    departure_time: str       # hora de saida do armazem
    last_client_departure: str
    arrival_home: str
    total_hours: float
    total_km: float
    fuel_cost: float
    total_boxes: int
    total_clients: int
    volume_pct: float
    notes: str = ""
    tiago_supports: bool = False  # True se Tiago apoia este motorista
