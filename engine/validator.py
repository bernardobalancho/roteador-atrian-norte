"""
Validador: compara output gerado com output real do GPT.

Metricas comparadas:
  1. Atribuicao de linhas (matricula por cliente)
  2. Ordem de entrega
  3. Horas trabalhadas por motorista
  4. Km por motorista
  5. Numero de clientes e caixas por viatura
  6. Janelas horarias respeitadas
"""
import re
from collections import defaultdict
from .loader import _open_xlsx, _read_xlsx_sheet


def load_real_bd(path):
    """Le a sheet BD do output real. Devolve lista de dicts."""
    zf, shared, sheet_map = _open_xlsx(path)
    bd_sheet = None
    for name in sheet_map:
        if name.upper() == 'BD':
            bd_sheet = name
            break
    if not bd_sheet:
        zf.close()
        return []

    rows = _read_xlsx_sheet(zf, sheet_map[bd_sheet], shared)
    zf.close()

    if not rows:
        return []

    data = []
    for row in rows[1:]:
        data.append({
            'client_code': row.get('A', ''),
            'client_name': row.get('B', ''),
            'article_code': row.get('C', ''),
            'shipping_address': row.get('R', ''),
            'plate': row.get('AA', ''),
            'driver': row.get('AB', ''),
            'order': row.get('AC', ''),
            'arrival': row.get('AD', ''),
            'obs_entrega': row.get('Z', ''),
        })
    return data


def load_real_resumo(path):
    """Le a sheet Resumo ROTEADO do output real."""
    zf, shared, sheet_map = _open_xlsx(path)
    sheet_name = None
    for name in sheet_map:
        if 'resumo' in name.lower() and 'gráfico' not in name.lower():
            sheet_name = name
            break
    if not sheet_name:
        zf.close()
        return []

    rows = _read_xlsx_sheet(zf, sheet_map[sheet_name], shared)
    zf.close()

    vehicles = []
    plate_pattern = re.compile(r'^[A-Z0-9]{2}-[A-Z0-9]{2}-[A-Z0-9]{2}$')
    for row in rows:
        plate = row.get('A', '')
        if plate and plate_pattern.match(plate):
            vehicles.append({
                'plate': plate,
                'driver': row.get('B', ''),
                'zones': row.get('C', ''),
                'boxes': _safe_int(row.get('D', '0')),
                'clients': _safe_int(row.get('E', '0')),
                'volume_pct': _safe_float(row.get('F', '0')),
                'departure': row.get('G', ''),
                'last_client': row.get('H', ''),
                'arrival_home': row.get('I', ''),
                'hours': _safe_float(row.get('J', '0')),
                'km': _safe_float(row.get('K', '0')),
                'fuel': _safe_float(row.get('L', '0')),
            })
    return vehicles


def _safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def validate(route_plans, real_output_path, lines=None):
    """
    Compara route_plans gerados com o output real.
    Devolve um dicionario com metricas de comparacao.
    """
    real_bd = load_real_bd(real_output_path)
    real_resumo = load_real_resumo(real_output_path)

    results = {
        'assignment_match': 0,
        'assignment_total': 0,
        'assignment_mismatches': [],
        'order_match': 0,
        'order_total': 0,
        'vehicle_comparison': [],
        'time_window_violations': [],
        'summary': '',
    }

    if not real_bd:
        results['summary'] = 'Sem dados reais para comparar.'
        return results

    # --- 1. Comparar atribuicoes (matricula por artigo+cliente) ---
    gen_map = {}
    for plan in route_plans:
        for astop in plan.stops:
            for line in astop.stop.lines:
                key = f"{line.client_code}_{line.article_code}_{line.shipping_address}"
                gen_map[key] = {
                    'plate': plan.vehicle.plate,
                    'order': f"{astop.delivery_order}/{astop.total_stops}",
                    'arrival': astop.estimated_arrival,
                }

    for real_line in real_bd:
        key = f"{real_line['client_code']}_{real_line['article_code']}_{real_line['shipping_address']}"
        results['assignment_total'] += 1

        gen = gen_map.get(key)
        if gen and gen['plate'] == real_line['plate']:
            results['assignment_match'] += 1
        else:
            gen_plate = gen['plate'] if gen else 'N/A'
            results['assignment_mismatches'].append({
                'client': real_line['client_code'],
                'article': real_line['article_code'],
                'real_plate': real_line['plate'],
                'gen_plate': gen_plate,
            })

        if gen and gen['order'] == real_line['order']:
            results['order_match'] += 1
        results['order_total'] += 1

    # --- 2. Comparar resumo por viatura ---
    gen_vehicles = {}
    for plan in route_plans:
        gen_vehicles[plan.vehicle.plate] = {
            'driver': plan.vehicle.driver,
            'boxes': plan.total_boxes,
            'clients': plan.total_clients,
            'hours': plan.total_hours,
            'km': plan.total_km,
            'fuel': plan.fuel_cost,
            'volume_pct': plan.volume_pct,
        }

    for rv in real_resumo:
        gv = gen_vehicles.get(rv['plate'], {})
        comp = {
            'plate': rv['plate'],
            'driver': rv['driver'],
            'real_boxes': rv['boxes'],
            'gen_boxes': gv.get('boxes', 0),
            'real_clients': rv['clients'],
            'gen_clients': gv.get('clients', 0),
            'real_hours': rv['hours'],
            'gen_hours': gv.get('hours', 0),
            'hours_diff': abs(rv['hours'] - gv.get('hours', 0)),
            'real_km': rv['km'],
            'gen_km': gv.get('km', 0),
            'km_diff': abs(rv['km'] - gv.get('km', 0)),
        }
        results['vehicle_comparison'].append(comp)

    # --- 3. Verificar janelas horarias ---
    for plan in route_plans:
        for astop in plan.stops:
            s = astop.stop
            if s.time_window_end is not None:
                if astop.arrival_minutes > s.time_window_end:
                    results['time_window_violations'].append({
                        'plate': plan.vehicle.plate,
                        'client': s.client_code,
                        'window_end': f"{s.time_window_end // 60:02d}:{s.time_window_end % 60:02d}",
                        'arrival': astop.estimated_arrival,
                        'delay_min': astop.arrival_minutes - s.time_window_end,
                    })

    # --- Resumo ---
    total = results['assignment_total']
    match = results['assignment_match']
    pct = (match / total * 100) if total else 0
    order_pct = (results['order_match'] / results['order_total'] * 100) if results['order_total'] else 0

    lines_summary = [
        f"Atribuição de linhas: {match}/{total} ({pct:.1f}% match)",
        f"Ordem de entrega: {results['order_match']}/{results['order_total']} ({order_pct:.1f}% match)",
        f"Violações de janela: {len(results['time_window_violations'])}",
    ]
    results['summary'] = '\n'.join(lines_summary)
    return results


def print_report(results):
    """Imprime relatorio de validacao em texto simples."""
    print("\n" + "=" * 60)
    print("  RELATÓRIO DE VALIDAÇÃO")
    print("=" * 60)

    print(f"\n{results['summary']}")

    if results['vehicle_comparison']:
        print("\n--- Comparação por viatura ---")
        print(f"{'Placa':<12} {'Motor.':<15} {'Cx Real':>8} {'Cx Gen':>8} "
              f"{'Cli R':>6} {'Cli G':>6} {'H Real':>7} {'H Gen':>7} "
              f"{'Km R':>7} {'Km G':>7}")
        print("-" * 100)
        for vc in results['vehicle_comparison']:
            print(f"{vc['plate']:<12} {vc['driver']:<15} "
                  f"{vc['real_boxes']:>8} {vc['gen_boxes']:>8} "
                  f"{vc['real_clients']:>6} {vc['gen_clients']:>6} "
                  f"{vc['real_hours']:>7.1f} {vc['gen_hours']:>7.1f} "
                  f"{vc['real_km']:>7.1f} {vc['gen_km']:>7.1f}")

    if results['assignment_mismatches']:
        n = len(results['assignment_mismatches'])
        print(f"\n--- Primeiros 20 de {n} mismatches de atribuição ---")
        for mm in results['assignment_mismatches'][:20]:
            print(f"  Cliente {mm['client']} art.{mm['article']}: "
                  f"real={mm['real_plate']}  gen={mm['gen_plate']}")

    if results['time_window_violations']:
        print(f"\n--- Violações de janela horária ({len(results['time_window_violations'])}) ---")
        for v in results['time_window_violations']:
            print(f"  {v['plate']} → Cliente {v['client']}: "
                  f"janela até {v['window_end']}, chegou {v['arrival']} "
                  f"(+{v['delay_min']} min)")

    print("\n" + "=" * 60)
