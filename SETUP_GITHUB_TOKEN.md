# Setup do GitHub Token para persistir configurações no Streamlit Cloud

Quando editas a página **Configurações** na app deployada, as alterações
precisam de ser guardadas de forma persistente. O Streamlit Cloud tem
filesystem read-only, por isso usamos a **API do GitHub** para commit automático.

## Setup (~5 min)

### 1. Criar um Personal Access Token (PAT) no GitHub

1. Abre https://github.com/settings/tokens?type=beta
2. Clica em **"Generate new token"** → **"Fine-grained personal access token"**
3. Configura:
   - **Name:** `Atrian Routing App`
   - **Expiration:** 1 ano (ou personalizado)
   - **Resource owner:** `bernardobalancho` (a tua conta)
   - **Repository access:** **"Only select repositories"** → escolhe `roteador-atrian-norte`
   - **Permissions:**
     - Repository permissions → **Contents** → **Read and write**
     - (Tudo o resto pode ficar a "No access")
4. Clica **"Generate token"** e **copia o valor** (começa por `github_pat_...`)
   ⚠️ Só é mostrado uma vez!

### 2. Adicionar o token aos Secrets do Streamlit Cloud

1. Abre https://share.streamlit.io/ → vai à tua app `roteador-atrian-norte`
2. Clica nos 3 pontos → **Settings** → **Secrets**
3. Cola o seguinte (adapta se já tiveres outros secrets):

```toml
APP_PASSWORD = "atrian2025"
GITHUB_TOKEN = "github_pat_COLA_AQUI_O_TEU_TOKEN"
GITHUB_REPO = "bernardobalancho/roteador-atrian-norte"
GITHUB_BRANCH = "main"
```

4. Clica **Save**. O Streamlit Cloud reinicia automaticamente.

### 3. Confirmar que funciona

1. Abre a app → faz login → vai à página **⚙️ Configurações**
2. Em cima deves ver: **💾 Modo de gravação: GitHub API**
3. Faz uma pequena alteração (ex: muda o nome do armazém)
4. Clica **💾 Guardar** → deves ver "Commit feito no GitHub"
5. Em ~1-2 minutos o Streamlit Cloud detecta o commit e re-deploy automaticamente

## Segurança

- O token tem acesso APENAS a este repositório, apenas a leitura+escrita de
  conteúdo (não pode apagar nem alterar config do repo)
- Renova o token anualmente (define alerta no calendário)
- Se algum dia precisares de revogar, vai a `Settings → Tokens → Revoke`

## Fallback local

Se não configurares o token, a página continua a funcionar **localmente**
(escreve nos `config_*.yaml` do disco). Útil para desenvolvimento.
No Streamlit Cloud sem token, as alterações seriam perdidas no próximo
re-deploy.
