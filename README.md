# comidinhas-bff

Scaffold inicial de um BFF/BFA em Python usando FastAPI.

## O que ja vem pronto

- estrutura base para evoluir o BFF
- endpoint `GET /health`
- endpoint `GET /api/v1/hello-world`
- endpoint `POST /api/v1/chat` para OpenAI
- endpoint `POST /api/v1/google-maps/restaurants/nearby` para Google Places
- endpoints de perfil/autenticacao em `POST /api/v1/profiles/signup`, `POST /api/v1/profiles/signin` e `GET /api/v1/profiles/me`
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
  modules/
    chat/
    google_places/
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
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_PROFILE_BUCKET`
- `SUPABASE_PROFILE_PHOTO_MAX_BYTES`

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

## Perfil no Supabase

1. Rode o SQL de [supabase/profile_setup.sql](/C:/Users/Admin/Desktop/projetos/comidinhas-bff/supabase/profile_setup.sql:1) no SQL Editor do Supabase para criar `public.profiles`, trigger e policies.
2. No Dashboard do Supabase, crie um bucket publico chamado `profile-photos`.
3. Depois disso, voce ja pode usar:

- `POST /api/v1/profiles/signup` para cadastrar usuario + perfil inicial
- `POST /api/v1/profiles/signin` para entrar
- `POST /api/v1/profiles/refresh` para renovar sessao
- `GET /api/v1/profiles/me` para buscar o perfil autenticado
- `PATCH /api/v1/profiles/me` para editar dados do perfil
- `PATCH /api/v1/profiles/me/credentials` para trocar username, email e senha
- `POST /api/v1/profiles/me/photo` para enviar foto
- `DELETE /api/v1/profiles/me/photo` para remover foto
- `DELETE /api/v1/profiles/me` para apagar apenas os dados do perfil
- `DELETE /api/v1/profiles/me/account` para apagar a conta inteira com o proprio token autenticado do usuario

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
