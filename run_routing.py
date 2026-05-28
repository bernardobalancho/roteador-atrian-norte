#!/usr/bin/env python3
"""
Ponto de entrada do roteador Atrian Norte.

Uso:
  python run_routing.py <input1_picking.xlsx> [--criteria input2.xlsx] [--validate real_output.xlsx]

Exemplo:
  python run_routing.py "Input 1 Mapa Picking Porto 20 Maio - Cópia.xlsx" \
    --criteria "Input 2 CRITERIOS, CONDIÇÕES E MAPA DE DISTRIBUIÇÃO v3.xlsx" \
    --validate "MAPA_PICKING_2026-05-20_ROTEADO_ATUALIZADO.xlsx"
"""
import sys
import os
import argparse
import yaml

from engine.loader import load_picking_map
from engine.router import route
from engine.writer import write_routed_map, write_pre_carga
from engine.validator import validate, print_report


def main():
    parser = argparse.ArgumentParser(description='Roteador Atrian Norte')
    parser.add_argument('input1', help='Ficheiro Excel Input 1 (Mapa de Picking)')
    parser.add_argument('--criteria', '-c',
                        help='Ficheiro Excel Input 2 (Critérios)')
    parser.add_argument('--config', default='config.yaml',
                        help='Ficheiro de configuração (default: config.yaml)')
    parser.add_argument('--validate', '-v',
                        help='Ficheiro real do GPT para validação')
    parser.add_argument('--output-dir', '-o', default='.',
                        help='Directoria de output (default: directoria atual)')
    args = parser.parse_args()

    # Carregar config
    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    print(f"Config carregado: {args.config}")

    # Carregar input
    print(f"\nA ler Input 1: {args.input1}")
    lines, expedition_date = load_picking_map(args.input1)
    print(f"  Linhas: {len(lines)}")
    print(f"  Data expedição: {expedition_date}")

    if not expedition_date:
        print("ERRO: Não foi possível extrair a data de expedição do ficheiro.")
        sys.exit(1)

    # Executar routing
    print("\n--- A calcular rotas ---")
    route_plans = route(lines, config, expedition_date)

    # Gerar outputs
    date_str = expedition_date.strftime('%Y-%m-%d')
    out_dir = args.output_dir

    os.makedirs(out_dir, exist_ok=True)
    routed_path = os.path.join(out_dir, f"MAPA_PICKING_{date_str}_ROTEADO.xlsx")
    precarga_path = os.path.join(out_dir, f"MAPA_PRE_CARGA_{date_str}.xlsx")

    print(f"\n--- A gerar outputs ---")
    write_routed_map(route_plans, lines, config, expedition_date,
                     args.criteria, routed_path)
    print(f"  Mapa Roteado: {routed_path}")

    write_pre_carga(route_plans, lines, config, expedition_date, precarga_path)
    print(f"  Mapa Pré-Carga: {precarga_path}")

    # Validar se pedido
    if args.validate:
        print(f"\n--- A validar contra: {args.validate} ---")
        results = validate(route_plans, args.validate, lines)
        print_report(results)

    print("\nConcluído.")


if __name__ == '__main__':
    main()
