# Comidinhas BFF — Guia Completo do Frontend

Base URL de todos os exemplos: `http://localhost:8000/api/v1`

Todo endpoint autenticado exige o header:
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

---

## 1. Autenticacao

### 1.1 Cadastro

```http
POST /profiles/signup
```
```json
{
  "email": "filipe@comidinhas.app",
  "password": "minhasenha123",
  "username": "filipe",
  "full_name": "Filipe Silva"
}
```

Resposta:
```json
{
  "user": { "id": "uuid-do-user", "email": "filipe@comidinhas.app", ... },
  "profile": { "id": "uuid-do-user", "username": "filipe", ... },
  "session": {
    "access_token": "eyJ...",
    "refresh_token": "abc123...",
    "expires_in": 3600,
    "expires_at": 1234567890
  },
  "email_confirmation_required": false
}
```

> Guarde `access_token` e `refresh_token` no storage seguro do app.
> O `expires_at` e o timestamp UNIX quando o token expira.

---

### 1.2 Login

```http
POST /profiles/signin
```
```json
{ "email": "filipe@comidinhas.app", "password": "minhasenha123" }
```

Mesma estrutura de resposta do signup.

---

### 1.3 Renovar sessao (refresh)

Chame isso antes de qualquer request quando `Date.now() / 1000 >= expires_at - 60`.

```http
POST /profiles/refresh
```
```json
{ "refresh_token": "abc123..." }
```

Resposta: nova sessao com novos tokens. **Salve os novos tokens imediatamente.**

---

### 1.4 Perfil do usuario logado

```http
GET /profiles/me
Authorization: Bearer <access_token>
```

---

### 1.5 Editar perfil

```http
PATCH /profiles/me
Authorization: Bearer <access_token>
```
```json
{
  "full_name": "Filipe Santos",
  "city": "Sao Paulo",
  "bio": "Amante de comida japonesa",
  "favorite_cuisine": "japonesa"
}
```

Todos os campos sao opcionais. Envie apenas o que mudou.

---

### 1.6 Trocar email ou senha

```http
PATCH /profiles/me/credentials
Authorization: Bearer <access_token>
```
```json
{
  "email": "novo@email.com",
  "password": "novasenha456"
}
```

---

### 1.7 Foto de perfil

```http
POST /profiles/me/photo
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file=<imagem.jpg>
```

```http
DELETE /profiles/me/photo
Authorization: Bearer <access_token>
```

---

## 2. Grupos e Casais

### 2.1 Criar o casal (fluxo principal)

Apos ambos os usuarios terem conta, qualquer um chama:

```http
POST /groups/seed/filipe-victor
Authorization: Bearer <access_token>
```
```json
{
  "filipe_email": "filipe@comidinhas.app",
  "victor_email": "victor@comidinhas.app"
}
```

Resposta:
```json
{ "group_id": "uuid-do-grupo", "message": "Casal Filipe e Victor configurado com sucesso." }
```

Ou, para criar um grupo generico e depois adicionar membros:

```http
POST /groups/
Authorization: Bearer <access_token>
```
```json
{
  "name": "Filipe e Victor",
  "type": "couple",
  "description": "Nosso app de restaurantes",
  "partner_email": "victor@comidinhas.app"
}
```

---

### 2.2 Contexto do usuario (endpoint mais usado na inicializacao do app)

Retorna tudo de uma vez: perfil, grupo ativo, papel no grupo e lista de grupos.

```http
GET /groups/me/context
Authorization: Bearer <access_token>
```

Resposta:
```json
{
  "user_id": "uuid",
  "profile_id": "uuid",
  "email": "filipe@comidinhas.app",
  "username": "filipe",
  "full_name": "Filipe Silva",
  "avatar_url": null,
  "active_group": {
    "id": "uuid-grupo",
    "name": "Filipe e Victor",
    "type": "couple",
    "members": [
      { "profile_id": "uuid-filipe", "role": "owner", "full_name": "Filipe Silva" },
      { "profile_id": "uuid-victor", "role": "member", "full_name": "Victor Lima" }
    ]
  },
  "active_role": "owner",
  "groups": [
    { "id": "uuid-grupo", "name": "Filipe e Victor", "type": "couple", "role": "owner" }
  ]
}
```

> **Dica de implementacao:** Chame este endpoint ao abrir o app (depois do login/refresh).
> Armazene `active_group.id` globalmente — e o `group_id` padrao para todas as operacoes.

---

### 2.3 Definir grupo ativo

Util se o usuario tiver mais de um grupo.

```http
POST /groups/active
Authorization: Bearer <access_token>
```
```json
{ "group_id": "uuid-grupo" }
```

---

### 2.4 Adicionar membro ao grupo

```http
POST /groups/{group_id}/members
Authorization: Bearer <access_token>
```
```json
{ "email": "amigo@email.com", "role": "member" }
```

---

### 2.5 Remover membro

```http
DELETE /groups/{group_id}/members/{profile_id}
Authorization: Bearer <access_token>
```

---

## 3. Lugares — Cadastro Manual

### 3.1 Criar lugar manualmente

O `group_id` e opcional — se omitido, usa o grupo ativo do usuario.

```http
POST /places/
Authorization: Bearer <access_token>
```
```json
{
  "name": "Restaurante Koi",
  "category": "Japones",
  "neighborhood": "Liberdade",
  "city": "Sao Paulo",
  "price_range": 3,
  "link": "https://maps.google.com/?q=Koi+Restaurante",
  "notes": "Otimo temaki, mas caro na sexta",
  "status": "quero_ir",
  "is_favorite": false
}
```

Campos de `price_range`: `1` ($) · `2` ($$) · `3` ($$$) · `4` ($$$$)

Status validos: `quero_ir` · `fomos` · `quero_voltar` · `nao_curti`

---

### 3.2 Editar qualquer campo do lugar

```http
PATCH /places/{place_id}
Authorization: Bearer <access_token>
```
```json
{
  "status": "fomos",
  "is_favorite": true,
  "notes": "Fomos em marco, adoramos o sushi combo!"
}
```

Envie apenas os campos que mudaram.

---

### 3.3 Remover lugar

```http
DELETE /places/{place_id}
Authorization: Bearer <access_token>
```

---

### 3.4 Detalhe do lugar (com fotos)

```http
GET /places/{place_id}
Authorization: Bearer <access_token>
```

Resposta inclui o array `photos` com todas as fotos ordenadas por `sort_order`.

---

### 3.5 Listagem com filtros e paginacao

```http
GET /places/?page=1&page_size=20&status=quero_ir&is_favorite=false
Authorization: Bearer <access_token>
```

Parametros disponiveis:

| Param | Tipo | Descricao |
|-------|------|-----------|
| `group_id` | string | UUID do grupo (padrao: grupo ativo) |
| `page` | int | Pagina (default: 1) |
| `page_size` | int | Itens por pagina (max: 100) |
| `search` | string | Busca por nome, categoria ou bairro |
| `category` | string | Filtra por categoria exata (parcial, case-insensitive) |
| `neighborhood` | string | Filtra por bairro (parcial, case-insensitive) |
| `status` | enum | `quero_ir`, `fomos`, `quero_voltar`, `nao_curti` |
| `is_favorite` | bool | `true` ou `false` |
| `price_range` | int | Exato: 1–4 |
| `price_range_min` | int | Faixa minima |
| `price_range_max` | int | Faixa maxima |
| `sort_by` | enum | `created_at`, `updated_at`, `name` |
| `sort_order` | enum | `asc`, `desc` |

Resposta:
```json
{
  "items": [ { "id": "...", "name": "Koi", "status": "quero_ir", "photos": [], ... } ],
  "page": 1,
  "page_size": 20,
  "total": 47,
  "has_more": true
}
```

---

## 4. Fotos de Lugares

### 4.1 Upload de foto

Primeira foto enviada vira capa automaticamente.

```http
POST /places/{place_id}/photos?set_as_cover=false
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file=<foto.jpg>
```

Resposta:
```json
{
  "id": "uuid-foto",
  "place_id": "uuid-lugar",
  "group_id": "uuid-grupo",
  "public_url": "https://seu-supabase.supabase.co/storage/v1/object/public/place-photos/...",
  "storage_path": "uuid-grupo/uuid-lugar/abc123.jpg",
  "is_cover": true,
  "sort_order": 0,
  "created_by": "uuid-usuario",
  "created_at": "2024-01-01T12:00:00Z"
}
```

> Limite: 10 fotos por lugar, max 5 MB por foto.
> Formatos aceitos: JPG, PNG, WEBP, GIF.

---

### 4.2 Listar fotos do lugar

```http
GET /places/{place_id}/photos
Authorization: Bearer <access_token>
```

Retorna array ordenado por `sort_order`.

---

### 4.3 Definir foto de capa

```http
PATCH /places/{place_id}/photos/{photo_id}/cover
Authorization: Bearer <access_token>
```

Nao precisa de body. Remove a capa anterior e define esta como nova capa.
Tambem atualiza `places.image_url` automaticamente.

---

### 4.4 Reordenar fotos

Envie a lista de IDs na nova ordem desejada:

```http
PATCH /places/{place_id}/photos/reorder
Authorization: Bearer <access_token>
```
```json
{ "photo_ids": ["uuid-foto-3", "uuid-foto-1", "uuid-foto-2"] }
```

Retorna a lista atualizada na nova ordem.

---

### 4.5 Remover foto

```http
DELETE /places/{place_id}/photos/{photo_id}
Authorization: Bearer <access_token>
```

Se a foto removida era a capa, a proxima foto na ordem assume automaticamente a capa.

---

## 5. Google Places — Autocomplete e Salvar

### 5.1 Fluxo completo

```
Campo de busca → autocomplete → usuario seleciona → detalhes → usuario confirma → save
```

---

### 5.2 Autocomplete (enquanto o usuario digita)

Chame a cada keystroke com debounce de ~300ms.

```http
POST /google-maps/places/autocomplete
```
```json
{
  "input": "Sushi Liberd",
  "location_bias": {
    "latitude": -23.5613,
    "longitude": -46.6563,
    "radius_meters": 10000
  },
  "included_primary_types": ["restaurant", "food", "cafe"],
  "session_token": "sessao-unica-uuid",
  "max_results": 5,
  "include_query_predictions": true
}
```

> `session_token`: gere um UUID unico no inicio de cada busca e reutilize durante a sessao de autocomplete. Muda ao usuario selecionar uma sugestao. Isso reduz custos da API.

Resposta:
```json
{
  "suggestions": [
    {
      "type": "place",
      "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
      "text": { "text": "Sushi Liberdade, Rua Galvao Bueno, Liberdade, Sao Paulo" },
      "main_text": { "text": "Sushi Liberdade", "matches": [{ "start_offset": 0, "end_offset": 5 }] },
      "secondary_text": { "text": "Rua Galvao Bueno, Liberdade, Sao Paulo" },
      "types": ["restaurant", "food", "establishment"],
      "distance_meters": 1240
    },
    {
      "type": "query",
      "text": { "text": "Sushi em Liberdade" },
      "main_text": { "text": "Sushi em Liberdade" }
    }
  ]
}
```

Use `main_text.text` para o nome em negrito e `secondary_text.text` para o endereco na sugestao.

---

### 5.3 Detalhes do lugar (apos o usuario selecionar)

```http
GET /google-maps/places/{place_id}
```

```http
GET /google-maps/places/ChIJN1t_tDeuEmsRUsoyG83frY4
```

Resposta:
```json
{
  "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
  "display_name": "Sushi Liberdade",
  "formatted_address": "R. Galvao Bueno, 540 - Liberdade, Sao Paulo - SP",
  "location": { "latitude": -23.561, "longitude": -46.634 },
  "neighborhood": "Liberdade",
  "city": "Sao Paulo",
  "rating": 4.6,
  "user_rating_count": 1248,
  "price_level": "PRICE_LEVEL_MODERATE",
  "price_range": 2,
  "primary_type": "japanese_restaurant",
  "primary_type_display_name": "Restaurante japones",
  "google_maps_uri": "https://maps.google.com/?cid=...",
  "website_uri": "https://sushiliberdade.com.br",
  "phone_number": "(11) 3456-7890",
  "open_now": true,
  "photo_uri": "https://lh3.googleusercontent.com/...",
  "photos": [
    {
      "photo_uri": "https://lh3.googleusercontent.com/...",
      "width_px": 1200,
      "height_px": 800,
      "attributions": [
        {
          "display_name": "Autor Teste",
          "uri": "https://maps.google.com/maps/contrib/...",
          "photo_uri": "https://lh3.googleusercontent.com/..."
        }
      ]
    }
  ],
  "types": ["japanese_restaurant", "restaurant", "food", "establishment"]
}
```

> `photo_uri` continua sendo a primeira foto para compatibilidade. Para galeria/carrossel, use `photos` (ate 10 imagens por lugar quando o Google retornar). Se houver `attributions`, exiba a atribuicao junto da foto.
> Exiba esses detalhes numa tela de preview antes do usuario confirmar.

---

### 5.4 Salvar lugar do Google no banco

```http
POST /google-maps/places/save
Authorization: Bearer <access_token>
```
```json
{
  "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
  "status": "quero_ir",
  "is_favorite": false,
  "notes": "Indica do Victor"
}
```

Retorna um `PlaceResponse` completo, igual ao de criacao manual.
Os campos `name`, `category`, `neighborhood`, `city`, `price_range`, `link` e `image_url` sao preenchidos automaticamente com os dados do Google.

> Apos salvar via Google, voce pode editar qualquer campo com `PATCH /places/{place_id}` e adicionar mais fotos com `POST /places/{place_id}/photos`.

---

## 6. Home — Tela Principal

```http
GET /home/?top_limit=5
Authorization: Bearer <access_token>
```

Parametros opcionais:
- `group_id`: UUID do grupo (padrao: grupo ativo)
- `top_limit`: quantos itens em cada lista (default: 5, max: 20)

Resposta:
```json
{
  "group": {
    "id": "uuid-grupo",
    "name": "Filipe e Victor",
    "type": "couple",
    "members": [
      { "profile_id": "uuid", "role": "owner", "full_name": "Filipe", "avatar_url": null },
      { "profile_id": "uuid", "role": "member", "full_name": "Victor", "avatar_url": null }
    ]
  },
  "counters": {
    "total_places": 42,
    "total_visited": 18,
    "total_favorites": 7,
    "total_want_to_go": 15
  },
  "top_favorites": [
    { "id": "uuid", "name": "Koi", "status": "quero_voltar", "is_favorite": true, "image_url": "...", ... }
  ],
  "latest_places": [ ... ],
  "want_to_go": [ ... ],
  "want_to_return": [ ... ]
}
```

---

## 7. Fluxos Recomendados de UI

### 7.1 Inicializacao do app (splash / loading)

```
1. Leia access_token e refresh_token do storage local
2. Se nenhum token: redirecione para Login
3. Se token expirado (expires_at <= now + 60s): POST /profiles/refresh
   - Sucesso: salve novos tokens, continue
   - Erro 401: redirecione para Login
4. GET /groups/me/context
   - Salve user_id, profile_id, active_group.id globalmente
5. Renderize a tela inicial com os dados do contexto
```

---

### 7.2 Adicionar um lugar (fluxo do botao "+")

**Opcao A — Via Google Places (recomendado)**
```
1. Usuario abre a tela de adicionar lugar
2. Campo de busca com debounce 300ms → POST /google-maps/places/autocomplete
3. Exibir sugestoes em dropdown
4. Usuario seleciona uma sugestao (type="place")
5. GET /google-maps/places/{place_id} → exibir preview
6. Usuario confirma / edita status, notas, favorito
7. POST /google-maps/places/save → lugar salvo
8. (Opcional) Adicionar fotos extras: POST /places/{id}/photos
```

**Opcao B — Cadastro manual**
```
1. Usuario abre formulario manual
2. Preenche nome, categoria, bairro, cidade, faixa de preco, link, notas, status
3. POST /places/ → lugar salvo
4. (Opcional) Adicionar fotos: POST /places/{id}/photos
```

---

### 7.3 Gerenciar fotos de um lugar

```
1. Abrir tela do lugar (GET /places/{id}) → recebe lista de photos
2. Exibir galeria em ordem de sort_order
3. A foto com is_cover=true e a capa exibida no card
4. Upload: POST /places/{id}/photos (multipart/form-data)
5. Definir capa: PATCH /places/{id}/photos/{photo_id}/cover
6. Reordenar (drag-and-drop): PATCH /places/{id}/photos/reorder com nova ordem
7. Remover: DELETE /places/{id}/photos/{photo_id}
```

---

### 7.4 Editar um lugar salvo

```
1. Tela de detalhe: GET /places/{place_id}
2. Usuario edita qualquer campo no formulario
3. PATCH /places/{place_id} com apenas os campos alterados
4. Exibir dados atualizados
```

Qualquer campo pode ser editado, incluindo lugares salvos via Google Places.

---

## 8. Referencia Rapida de Endpoints

### Autenticacao
| Metodo | Path | Descricao |
|--------|------|-----------|
| POST | `/profiles/signup` | Cadastro |
| POST | `/profiles/signin` | Login |
| POST | `/profiles/refresh` | Renovar tokens |
| POST | `/profiles/signout` | Logout |
| GET | `/profiles/me` | Perfil atual |
| PATCH | `/profiles/me` | Editar perfil |
| PATCH | `/profiles/me/credentials` | Trocar email/senha |
| POST | `/profiles/me/photo` | Foto de perfil |
| DELETE | `/profiles/me/photo` | Remover foto de perfil |

### Grupos
| Metodo | Path | Descricao |
|--------|------|-----------|
| GET | `/groups/me/context` | Contexto completo do usuario |
| GET | `/groups/` | Listar meus grupos |
| POST | `/groups/` | Criar grupo |
| GET | `/groups/{id}` | Detalhe do grupo |
| PATCH | `/groups/{id}` | Editar grupo |
| DELETE | `/groups/{id}` | Remover grupo |
| POST | `/groups/{id}/members` | Adicionar membro |
| DELETE | `/groups/{id}/members/{pid}` | Remover membro |
| POST | `/groups/active` | Definir grupo ativo |
| POST | `/groups/seed/filipe-victor` | Seed inicial |

### Lugares
| Metodo | Path | Descricao |
|--------|------|-----------|
| GET | `/places/` | Listar com filtros e paginacao |
| POST | `/places/` | Criar lugar manual |
| GET | `/places/{id}` | Detalhe + fotos |
| PATCH | `/places/{id}` | Editar qualquer campo |
| DELETE | `/places/{id}` | Remover lugar |

### Fotos
| Metodo | Path | Descricao |
|--------|------|-----------|
| GET | `/places/{id}/photos` | Listar fotos |
| POST | `/places/{id}/photos` | Upload de foto |
| PATCH | `/places/{id}/photos/{photo_id}/cover` | Definir capa |
| PATCH | `/places/{id}/photos/reorder` | Reordenar |
| DELETE | `/places/{id}/photos/{photo_id}` | Remover foto |

### Google Places
| Metodo | Path | Descricao |
|--------|------|-----------|
| POST | `/google-maps/places/autocomplete` | Sugestoes em tempo real |
| GET | `/google-maps/places/{place_id}` | Detalhes do lugar |
| POST | `/google-maps/places/save` | Salvar do Google no banco |
| POST | `/google-maps/restaurants/nearby` | Restaurantes proximos |

### Home
| Metodo | Path | Descricao |
|--------|------|-----------|
| GET | `/home/` | Agregado da home |
