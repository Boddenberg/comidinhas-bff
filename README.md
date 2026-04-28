# comidinhas-bff

Scaffold inicial de um BFF/BFA em Python usando FastAPI.

## O que ja vem pronto

- estrutura base para evoluir o BFF
- endpoint `GET /health`
- endpoint `GET /api/v1/hello-world`
- endpoint `POST /api/v1/chat` para OpenAI
- endpoint `POST /api/v1/google-maps/restaurants/nearby` para Google Places
- endpoint `POST /api/v1/infobip/whatsapp/template` para envio de template WhatsApp via Infobip
- endpoints no-auth de perfis, contextos, lugares, guias, decisao e recomendacao por IA em `/api/v1/perfis`, `/api/v1/grupos`, `/api/v1/lugares`, `/api/v1/guias`, `/api/v1/ia/decidir-restaurante` e `/api/v1/ia/recomendar-restaurantes`
- docs automaticas em `http://127.0.0.1:8000/docs`
- `main.py` na raiz para rodar direto no PyCharm

## Arquitetura inicial

```text
app/
  api/
    dependencies.py
    error_handlers.py
    routes/
    v1/routes/
  core/
    config.py
    errors.py
    lifespan.py
  integrations/
    openai/client.py
    google_places/client.py
    infobip/client.py
    supabase/client.py
  modules/
    chat/
    google_places/
    infobip/
    profiles/
    groups/
    places/
    home/
```

### Como esta dividido

- `api/`: camada HTTP e injecao de dependencias
- `core/`: configuracao, ciclo de vida da app e erros comuns
- `integrations/`: clientes para servicos externos
- `modules/`: contratos e casos de uso por funcionalidade

## Variaveis de ambiente

Copie `.env.example` para `.env` e preencha:

```powershell
Copy-Item .env.example .env
```

Campos esperados:

- `OPENAI_API_KEY`
- `OPENAI_CHAT_MODEL`
- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_PLACES_DEFAULT_LANGUAGE_CODE`
- `GOOGLE_PLACES_DEFAULT_REGION_CODE`
- `GOOGLE_PLACES_MAX_PHOTOS_PER_PLACE`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_PROFILE_BUCKET`
- `SUPABASE_PROFILE_PHOTO_MAX_BYTES`
- `SUPABASE_GROUP_BUCKET`
- `SUPABASE_GROUP_PHOTO_MAX_BYTES`
- `INFOBIP_BASE_URL`
- `INFOBIP_API_KEY`
- `INFOBIP_WHATSAPP_FROM`
- `INFOBIP_DEFAULT_TEMPLATE_NAME`
- `INFOBIP_DEFAULT_LANGUAGE`

### Exemplo Infobip WhatsApp

Com `INFOBIP_API_KEY` e `INFOBIP_WHATSAPP_FROM` configurados:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/infobip/whatsapp/template `
  -H "Content-Type: application/json" `
  -d '{"to":"5511999999999","placeholders":["Boddenberg"]}'
```

## Como rodar

1. Crie e ative um ambiente virtual:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Instale as dependencias:

```powershell
pip install -e .[dev]
```

3. Rode a aplicacao:

```powershell
python main.py
```

4. Teste os endpoints:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/api/v1/hello-world`
- `http://127.0.0.1:8000/docs`

## Rodando no PyCharm

- abra o projeto
- configure o interpretador para `.\.venv\Scripts\python.exe`
- execute o arquivo `main.py`

## Testes

```powershell
pytest
```

## Setup no Supabase

### Fluxo no-auth atual

Rode o SQL de [supabase/schema.sql](supabase/schema.sql) no SQL Editor do Supabase. Ele cria `public.perfis`, `public.grupos`, `public.lugares` e `public.guias` sem depender de Supabase Auth.

Se o banco no-auth ja existe, rode tambem [supabase/group_join_requests_setup.sql](supabase/group_join_requests_setup.sql) para adicionar codigo curto de grupo, foto do grupo e solicitacoes de entrada sem dropar dados.

O fluxo principal fica:

- `POST /api/v1/perfis/` cadastra uma pessoa e cria automaticamente o espaco individual dela.
- `GET /api/v1/perfis/{perfil_id}/contextos` lista os espacos selecionaveis do perfil.
- `POST /api/v1/grupos/` cria um contexto `individual`, `casal` ou `grupo` com membros ligados por `perfil_id`; para `grupo`, informe `dono_perfil_id`.
- `GET /api/v1/grupos/codigo/{codigo}` busca um grupo pelo codigo numerico de 6 digitos.
- `POST /api/v1/grupos/codigo/{codigo}/solicitacoes` cria uma solicitacao de entrada para o dono aprovar.
- `GET /api/v1/grupos/{grupo_id}/solicitacoes?responsavel_perfil_id=...` lista solicitacoes (somente dono).
- `POST /api/v1/grupos/{grupo_id}/solicitacoes/{solicitacao_id}/aceitar` aceita uma solicitacao e adiciona o perfil como membro.
- `POST /api/v1/grupos/{grupo_id}/solicitacoes/{solicitacao_id}/recusar` recusa uma solicitacao.
- `PATCH /api/v1/grupos/{grupo_id}/membros/{perfil_id}/papel` permite ao dono tornar um membro `administrador` ou voltar para `membro`.
- `PATCH /api/v1/grupos/{grupo_id}` atualiza nome, descricao ou foto via URL quando `responsavel_perfil_id` for dono ou administrador; mudancas de dono/membros continuam restritas ao dono.
- `POST /api/v1/grupos/{grupo_id}/foto?responsavel_perfil_id=...` envia ou substitui a foto do grupo (dono ou administrador).
- `GET /api/v1/grupos/?perfil_id=...` lista os contextos de um perfil.
- `GET /api/v1/lugares/?grupo_id=...` lista restaurantes do contexto selecionado.
- `POST /api/v1/lugares/` adiciona restaurante ao contexto; use `adicionado_por_perfil_id` para registrar quem adicionou.
- `GET /api/v1/guias/?grupo_id=...` lista guias customizados do contexto.
- `POST /api/v1/guias/` cria um guia com nome, descricao e `lugar_ids`.
- `POST /api/v1/guias/{guia_id}/lugares` adiciona restaurante ao guia.
- `PATCH /api/v1/guias/{guia_id}/lugares/reordenar` reordena restaurantes do guia.
- `POST /api/v1/ia/decidir-restaurante` escolhe restaurante com IA por escopo: `todos`, `favoritos`, `quero_ir` ou `guia`.
- `POST /api/v1/ia/recomendar-restaurantes` interpreta uma mensagem livre, busca no Supabase e no Google Places, e retorna opcoes estruturadas para o front.
- `GET /api/v1/home/?grupo_id=...` retorna o agregado do contexto selecionado.

### Legado com auth

Os scripts abaixo pertencem ao fluxo antigo com `profiles`, `groups`, `places` e bearer token. Para o app no-auth, prefira o `schema.sql` acima.

### 1. Perfil base

Rode o SQL de [supabase/profile_setup.sql](supabase/profile_setup.sql) no SQL Editor do Supabase para criar `public.profiles`, trigger e policies.

No Dashboard do Supabase, crie um bucket publico chamado `profile-photos`.

### 2. Grupos e Lugares

Rode o SQL de [supabase/groups_places_setup.sql](supabase/groups_places_setup.sql) para criar:

- `public.groups` — casais ou grupos
- `public.group_members` — membros de cada grupo
- `public.places` — lugares/restaurantes vinculados ao grupo
- triggers de auditoria (`created_by`, `updated_by`, `updated_at`)
- RLS (Row Level Security) para todas as tabelas
- funcoes RPC: `home_summary`, `set_active_group`, `seed_couple_group`, `seed_filipe_victor`

### 3. Dados iniciais (Filipe e Victor)

Apos criar as contas de Filipe e Victor via `POST /api/v1/profiles/signup`, use um dos dois caminhos:

**Via API** (autenticado como qualquer um dos dois):
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/groups/seed/filipe-victor" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filipe_email":"filipe@comidinhas.app","victor_email":"victor@comidinhas.app"}'
```

**Via SQL Editor do Supabase**:
```sql
select public.seed_filipe_victor('filipe@comidinhas.app', 'victor@comidinhas.app');
```

Depois disso, voce ja pode usar:

**Perfil / Autenticacao**
- `POST /api/v1/profiles/signup` — cadastra usuario + perfil inicial
- `POST /api/v1/profiles/signin` — autentica por email e senha
- `POST /api/v1/profiles/refresh` — renova a sessao
- `GET /api/v1/profiles/me` — perfil autenticado
- `PATCH /api/v1/profiles/me` — edita dados do perfil
- `PATCH /api/v1/profiles/me/credentials` — troca username, email e senha
- `POST /api/v1/profiles/me/photo` — envia foto de perfil
- `DELETE /api/v1/profiles/me/photo` — remove foto
- `DELETE /api/v1/profiles/me` — apaga dados do perfil
- `DELETE /api/v1/profiles/me/account` — apaga a conta inteira

**Grupos / Casais**
- `GET /api/v1/groups/me/context` — contexto atual: perfil, grupo ativo e papel
- `GET /api/v1/groups/` — lista grupos do usuario
- `POST /api/v1/groups/` — cria grupo ou casal (partner_email ou partner_profile_id)
- `GET /api/v1/groups/{group_id}` — detalhe do grupo com membros
- `PATCH /api/v1/groups/{group_id}` — atualiza nome/tipo/descricao
- `DELETE /api/v1/groups/{group_id}` — remove o grupo
- `POST /api/v1/groups/{group_id}/members` — adiciona membro
- `DELETE /api/v1/groups/{group_id}/members/{profile_id}` — remove membro
- `POST /api/v1/groups/active` — define o grupo ativo
- `POST /api/v1/groups/seed/filipe-victor` — cria o casal Filipe e Victor

**Lugares / Restaurantes**
- `GET /api/v1/places/` — listagem paginada com busca e filtros
  - Query params: `group_id`, `page`, `page_size`, `search`, `category`, `neighborhood`, `status`, `is_favorite`, `price_range`, `price_range_min`, `price_range_max`, `sort_by`, `sort_order`
- `POST /api/v1/places/` — adiciona um lugar
- `GET /api/v1/places/{place_id}` — detalhe do lugar
- `PATCH /api/v1/places/{place_id}` — atualiza campos
- `DELETE /api/v1/places/{place_id}` — remove o lugar

**Home (agregador)**
- `GET /api/v1/home/` — retorna grupo, contadores, favoritos, ultimos adicionados, fila "quero ir" e "quero voltar"
  - Query params: `group_id`, `top_limit`

**Google Places — Autocomplete e Save**
- `POST /api/v1/google-maps/places/autocomplete` — sugestoes em tempo real enquanto o usuario digita
  - Body: `input`, `location_bias`, `included_primary_types`, `session_token`, `max_results`, ...
  - Retorna lista de `PlacePrediction` e/ou `QueryPrediction`
- `GET /api/v1/google-maps/places/{place_id}` — detalhes completos de um lugar (nome, categoria, bairro, cidade, preco, fotos, coordenadas)
- `POST /api/v1/google-maps/places/save` — busca detalhes no Google e salva direto no banco do grupo
  - Body: `place_id`, `group_id` (opcional, usa grupo ativo), `status`, `is_favorite`, `notes`
  - Retorna o `PlaceResponse` criado no banco

## Exemplos de chamadas

### Chat OpenAI

```bash
curl --request POST "http://127.0.0.1:8000/api/v1/chat" \
  --header "Content-Type: application/json" \
  --data "{\"message\":\"Quero uma sugestao de jantar leve para hoje\"}"
```

### Chat OpenAI com historico

```bash
curl --request POST "http://127.0.0.1:8000/api/v1/chat" \
  --header "Content-Type: application/json" \
  --data "{\"message\":\"Agora me passe uma versao vegetariana\",\"history\":[{\"role\":\"user\",\"content\":\"Quero uma sugestao de jantar leve para hoje\"},{\"role\":\"assistant\",\"content\":\"Uma boa opcao e salmao com legumes assados.\"}]}"
```

### Restaurantes proximos via Google Places

```bash
curl --request POST "http://127.0.0.1:8000/api/v1/google-maps/restaurants/nearby" \
  --header "Content-Type: application/json" \
  --data "{\"latitude\":-23.55052,\"longitude\":-46.633308,\"radius_meters\":1500,\"max_results\":5,\"included_types\":[\"restaurant\"],\"rank_preference\":\"POPULARITY\"}"
```
