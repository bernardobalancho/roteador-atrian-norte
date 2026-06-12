"""
Persistencia de configuracoes: escreve config_<regiao>.yaml.

Duas estrategias:
1. **Local** (dev): escreve diretamente no ficheiro YAML do disco
2. **GitHub API** (cloud): commita o ficheiro via API ao repo, persistindo entre
   re-deploys do Streamlit Cloud

Estrategia escolhida automaticamente: se existir GITHUB_TOKEN nos secrets,
usa GitHub API. Caso contrario, fallback para local.
"""
import os
import yaml
import base64
import requests
from datetime import datetime


def _yaml_dump(config: dict) -> str:
    """Serializa config para YAML preservando ordem e estilo."""
    return yaml.safe_dump(
        config, allow_unicode=True, sort_keys=False,
        default_flow_style=False, indent=2, width=120
    )


def _config_path(region: str) -> str:
    """Caminho absoluto para o ficheiro config_<regiao>.yaml."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, f'config_{region.lower()}.yaml')


def _save_local(region: str, config: dict) -> dict:
    """Escreve config no disco local. Devolve resultado."""
    path = _config_path(region)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_yaml_dump(config))
        return {
            'success': True,
            'mode': 'local',
            'path': path,
            'message': f'Guardado localmente em {path}',
        }
    except Exception as e:
        return {
            'success': False,
            'mode': 'local',
            'message': f'Erro a guardar localmente: {e}',
        }


def _get_secret(key: str, default=None):
    """Le um secret do Streamlit (se disponivel) ou variavel de ambiente."""
    try:
        import streamlit as st
        try:
            return st.secrets.get(key, os.environ.get(key, default))
        except Exception:
            return os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def _save_github(region: str, config: dict, user_label: str = "App User") -> dict:
    """
    Commita o config via GitHub API.

    Requer nos secrets do Streamlit Cloud:
      - GITHUB_TOKEN: Personal Access Token com scope 'repo'
      - GITHUB_REPO: "owner/repo" (e.g. "bernardobalancho/roteador-atrian-norte")
      - GITHUB_BRANCH: branch (default: "main")
    """
    token = _get_secret('GITHUB_TOKEN')
    repo = _get_secret('GITHUB_REPO', 'bernardobalancho/roteador-atrian-norte')
    branch = _get_secret('GITHUB_BRANCH', 'main')

    if not token:
        return {'success': False, 'mode': 'github',
                'message': 'GITHUB_TOKEN nao configurado nos secrets'}

    file_path = f'config_{region.lower()}.yaml'
    api_url = f'https://api.github.com/repos/{repo}/contents/{file_path}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    try:
        # 1. Obter SHA do ficheiro atual (necessario para update)
        r = requests.get(api_url, headers=headers,
                         params={'ref': branch}, timeout=15)
        if r.status_code == 200:
            current_sha = r.json().get('sha')
        elif r.status_code == 404:
            current_sha = None  # ficheiro novo
        else:
            return {'success': False, 'mode': 'github',
                    'message': f'GitHub GET falhou: {r.status_code} {r.text[:200]}'}

        # 2. Preparar conteudo (base64)
        content = _yaml_dump(config)
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')

        # 3. Commit
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        commit_msg = (f"Atualizar {file_path} via UI ({timestamp})\n\n"
                      f"Autor: {user_label}")
        payload = {
            'message': commit_msg,
            'content': content_b64,
            'branch': branch,
        }
        if current_sha:
            payload['sha'] = current_sha

        r = requests.put(api_url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            commit_url = r.json().get('commit', {}).get('html_url', '')
            return {
                'success': True, 'mode': 'github',
                'message': f'Commit feito no GitHub. O Streamlit Cloud vai re-deploy em ~1 min.',
                'commit_url': commit_url,
                'path': file_path,
            }
        else:
            return {'success': False, 'mode': 'github',
                    'message': f'GitHub PUT falhou: {r.status_code} {r.text[:300]}'}

    except Exception as e:
        return {'success': False, 'mode': 'github',
                'message': f'Erro GitHub API: {e}'}


def save_config(region: str, config: dict, user_label: str = "App User") -> dict:
    """
    Guarda config da regiao. Escolhe estrategia automaticamente.

    Returns dict com:
      success: bool
      mode: "local" ou "github"
      message: descricao do resultado
      commit_url: URL do commit (se modo github)
    """
    if _get_secret('GITHUB_TOKEN'):
        return _save_github(region, config, user_label)
    return _save_local(region, config)


def storage_mode() -> str:
    """Devolve o modo de armazenamento ativo: 'github' ou 'local'."""
    return 'github' if _get_secret('GITHUB_TOKEN') else 'local'
