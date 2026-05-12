# Base de Restaurantes de São Paulo

Base local usada pelo BFF para busca e recuperação sem dependência de Google Maps.

Arquivos principais:

- `source.md`: arquivo Markdown original importado.
- `index.json`: índice estruturado consumido pela API.
- `chunks/by_restaurant/*.md`: chunks pequenos, um restaurante por arquivo.
- `chunks/by_category/*.md`: chunks agregados por categoria gastronômica.

Para regenerar a base a partir de um novo Markdown:

```powershell
python scripts\build_restaurant_knowledge_base.py "C:\caminho\para\restaurantes.md" --output-dir app\data\restaurant_knowledge\sao_paulo
```

O parser considera como restaurantes as seções numeradas `## 1.` até `## 30.`
e cada bloco `### Nome do restaurante` dentro delas.
