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

- `WEB_APP_BASE_URL`
- `WEB_GROUP_INVITE_PATH`
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

## Criar guia com IA

A feature "Criar guia com IA" permite que o usuario cole um texto desestruturado
copiado da internet (ranking, materia, lista, guia gastronomico) e o backend
monte um guia completo dentro do Comidinhas, com restaurantes, fotos, dados do
Google Maps, sugestoes para o grupo e pendencias claras de revisao opcional.

### Como funciona

1. O frontend chama `POST /api/v1/guias/ia/imports` com o texto e recebe
   imediatamente um `job_id` (HTTP 202). Nada bloqueia o request.
2. O backend executa o pipeline em segundo plano (asyncio task), atualizando
   o estado do job a cada etapa: `sanitizing_text`, `classifying_content`,
   `extracting_guide_metadata`, `extracting_restaurants`,
   `matching_internal_restaurants`, `searching_google_places`,
   `enriching_places`, `selecting_photos`, `calculating_group_suggestions`,
   `creating_guide`, `completed` ou `completed_with_warnings`.
3. O frontend faz polling em `GET /api/v1/guias/ia/imports/{job_id}` para
   exibir progresso ("Lendo o texto", "Identificando restaurantes", etc.).
4. Quando o job termina, `guia_id` aparece no payload do job e o app abre
   o guia via `GET /api/v1/guias/ia/{guia_id}`.

### Resiliencia

- Cada etapa tem retry com backoff e nao morre por timeout de request.
- Falhas parciais (ex: 3 itens nao acharam Place ID) NAO abortam a importacao.
  O guia e criado com pendencias e o usuario pode resolver depois.
- Se o LLM falhar, o extractor cai em um parser deterministico.
- Se o Google Maps falhar/atingir limite, os itens ficam com status
  `nao_encontrado`/`pendente` e o guia segue.
- Textos nao gastronomicos (receita, review individual, conteudo nao
  relacionado a comida) terminam com status `invalid_content` e mensagem
  amigavel ao usuario.

### Privacidade nas sugestoes

As sugestoes do guia ("Melhor para hoje", "Mais facil para todos", etc.)
usam apenas a `cidade` salva no perfil dos membros do grupo. Nenhum endereco
individual e exposto a outros membros nem enviado para o LLM. Toda explicacao
e agregada ("tempo medio de deslocamento baixo para o grupo"), nunca
"fica perto da casa do Fulano".

### Variaveis de ambiente da feature

- `GUIAS_AI_ENABLED` (default `true`)
- `GUIAS_AI_CLASSIFIER_MODEL` / `GUIAS_AI_EXTRACTOR_MODEL` (default `gpt-4o-mini`)
- `GUIAS_AI_TEXT_MIN_CHARS` / `GUIAS_AI_TEXT_MAX_CHARS`
- `GUIAS_AI_MAX_ITEMS_PER_GUIDE` / `GUIAS_AI_MIN_ITEMS_TO_CREATE_GUIDE`
- `GUIAS_AI_MAX_PLACES_LOOKUPS_PER_JOB` / `GUIAS_AI_PLACES_CONCURRENCY`
- `GUIAS_AI_MATCH_STRONG_SCORE` / `GUIAS_AI_MATCH_WEAK_SCORE`
- `GUIAS_AI_STEP_MAX_ATTEMPTS` / `GUIAS_AI_JOB_MAX_SECONDS`
- `OPENAI_API_KEY` (obrigatorio) e `GOOGLE_MAPS_API_KEY` (recomendado).

### APIs do Google usadas

A feature reutiliza o cliente existente em `app/integrations/google_places`
e usa `places:searchText` com `FieldMask` enxuto para localizar candidatos e
`places:photos` para a capa do guia. Nenhum dado sensivel do grupo e enviado
ao Google.

### Detalhes da arquitetura

**Extracao por chunks com overlap.** Textos longos (rankings TOP 50/100) sao
divididos em pedacos de ~12k chars com 1.5k de overlap e processados em
paralelo. Itens duplicados na fronteira sao deduplicados por nome
normalizado e place_id no merge.

**Guia incremental.** O guia esqueleto e criado logo apos a extracao
(antes do enriquecimento Google), entao o frontend pode navegar para a URL
do guia enquanto os cards ainda estao chegando.

**Auto-criacao de lugares.** Itens com match Google de alta confianca e
`place_id` que ainda nao existem no banco do grupo viram `lugares`
automaticamente, ja com status `quero_ir`. O usuario pode marcar
favorito/quero_voltar/etc. imediatamente.

**Cache em processo.** Buscas no Google Places sao cacheadas em memoria
(TTL+LRU) para reduzir custo quando varios grupos importam textos
similares. Configuravel por `GUIAS_AI_PLACES_CACHE_*`.

**Maquina de estados resiliente.** Jobs tem `cancelled` como estado
adicional, suporte a retry (`/reexecutar`) e watchdog para marcar como
falhos os que ficaram parados (deploy no meio do processamento).
Idempotencia por hash do texto: se o mesmo texto for enviado nas ultimas
24h e ja virou guia, devolvemos o job antigo sem refazer.

**Sugestoes mais inteligentes.** "Mais facil para todos" agora usa
Haversine entre cada candidato e o centroide dos lugares ja salvos pelo
grupo (dado proprio do grupo, sem expor membros). Se o grupo nao tiver
lugares com lat/long, cai para o fallback por cidade.

**Streaming.** A rota `/imports/{job_id}/stream` emite Server-Sent Events
para o frontend atualizar a UI sem polling.

### Limitacoes da primeira versao

- O calculo de proximidade usa o centroide dos lugares ja salvos pelo
  grupo. Quando enderecos por membro forem suportados, basta evoluir
  `SuggestionEngine` sem mexer em nada da pipeline.
- O guia gerado por IA convive com guias manuais na mesma tabela `guias`
  (`tipo_guia = 'ia'`). Os itens ricos ficam em `guia_itens`.
- Watchdog precisa ser disparado externamente (cron ou hit manual em
  `POST /api/v1/guias/ia/imports/watchdog`); nao roda sozinho.
- Cache de Places e in-process (perde-se em cada deploy). Para volume alto
  vale promover para Redis depois.
- Sem testes automatizados nesta etapa (por escolha de escopo).

## Setup no Supabase

### Fluxo no-auth atual

Rode o SQL de [supabase/schema.sql](supabase/schema.sql) no SQL Editor do Supabase. Ele cria `public.perfis`, `public.grupos`, `public.lugares` e `public.guias` sem depender de Supabase Auth.

Se o banco no-auth ja existe, rode tambem [supabase/group_join_requests_setup.sql](supabase/group_join_requests_setup.sql) para adicionar codigo curto de grupo, foto do grupo e solicitacoes de entrada sem dropar dados.

Para habilitar a feature "Criar guia com IA", aplique nesta ordem:

1. [supabase/migrations/20260502120000_ai_guides.sql](supabase/migrations/20260502120000_ai_guides.sql)
   — colunas aditivas em `guias`, novas tabelas `guia_itens` e `guia_ai_jobs`.
2. [supabase/migrations/20260502130000_ai_guides_v2.sql](supabase/migrations/20260502130000_ai_guides_v2.sql)
   — estado `cancelled`, coluna `parent_job_id` (retry) e indice util pro
   watchdog detectar jobs travados.

Ambas sao 100% aditivas: nada e removido e os guias manuais existentes
continuam funcionando sem alteracao.

O fluxo principal fica:

- `POST /api/v1/perfis/` cadastra uma pessoa e cria automaticamente o espaco individual dela.
- `GET /api/v1/perfis/{perfil_id}/contextos` lista os espacos selecionaveis do perfil.
- `POST /api/v1/grupos/` cria um contexto `individual`, `casal` ou `grupo` com membros ligados por `perfil_id`; para `grupo`, informe `dono_perfil_id`.
- `GET /api/v1/grupos/{grupo_id}/convite?responsavel_perfil_id=...` gera link, mensagem copiavel e payload para QR code.
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
- `POST /api/v1/guias/ia/imports` cria um job de importacao "Criar guia com IA" a partir de um texto colado e retorna `job_id` (HTTP 202).
- `GET /api/v1/guias/ia/imports/{job_id}` consulta o progresso e estado final do job.
- `GET /api/v1/guias/ia/{guia_id}` retorna o guia gerado por IA com itens enriquecidos, sugestoes e metadados.
- `PATCH /api/v1/guias/ia/{guia_id}` edita nome, descricao, categoria, regiao e cidade principal.
- `PATCH /api/v1/guias/ia/{guia_id}/capa` troca a imagem de capa (URL livre ou foto de um item).
- `PATCH /api/v1/guias/ia/{guia_id}/itens/reordenar` reordena os itens do guia.
- `PATCH /api/v1/guias/ia/{guia_id}/itens/{item_id}` edita um item (associar lugar, status, foto).
- `DELETE /api/v1/guias/ia/{guia_id}/itens/{item_id}` remove um item do guia.
- `PATCH /api/v1/guias/ia/{guia_id}/itens/bulk` confirma, descarta ou associa varios itens em uma so chamada.
- `POST /api/v1/guias/ia/imports/{job_id}/cancelar` cancela um job em andamento.
- `POST /api/v1/guias/ia/imports/{job_id}/reexecutar` reprocessa um job cancelado/falho.
- `POST /api/v1/guias/ia/imports/watchdog` marca como `failed` jobs travados sem atualizacao.
- `GET /api/v1/guias/ia/imports/{job_id}/stream` recebe o progresso por Server-Sent Events.
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
