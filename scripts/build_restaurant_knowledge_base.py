from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECTION_RE = re.compile(r"^##\s+(?P<number>\d+)\.\s+(?P<title>.+?)\s*$")
ENTRY_RE = re.compile(r"^###\s+(?P<name>.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+\*\*(?P<key>[^*]+):\*\*\s*(?P<value>.*)$")


def parse_markdown(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines()

    entries: list[dict[str, Any]] = []
    categories: dict[str, dict[str, Any]] = {}
    current_section: dict[str, Any] | None = None
    current_entry: dict[str, Any] | None = None
    active_restaurant_section = False

    def flush_entry() -> None:
        nonlocal current_entry
        if current_entry is None or current_section is None:
            current_entry = None
            return

        lines = list(current_entry["lines"])
        while lines and (not lines[-1].strip() or lines[-1].strip() == "---"):
            lines.pop()

        fields = current_entry["fields"]
        address = fields.get("endereco")
        category_id = current_section["id"]
        entry = {
            "id": "",
            "nome": current_entry["name"],
            "categoria_id": category_id,
            "categoria": current_section["title"],
            "tipo": fields.get("tipo"),
            "endereco": address,
            "bairro": extract_neighborhood(address),
            "cidade": "São Paulo",
            "distincao": fields.get("distincao"),
            "descricao": fields.get("descricao"),
            "campos_extras": {
                key: value
                for key, value in fields.items()
                if key not in {"tipo", "endereco", "distincao", "descricao"}
            },
            "markdown": "\n".join(lines).strip(),
            "fonte_chunk": "",
        }
        entries.append(entry)
        categories[category_id]["total_restaurantes"] += 1
        current_entry = None

    for line in lines:
        section_match = SECTION_RE.match(line)
        if section_match:
            flush_entry()
            number = int(section_match.group("number"))
            active_restaurant_section = 1 <= number <= 30
            if not active_restaurant_section:
                current_section = None
                continue

            title = section_match.group("title").strip()
            category_id = f"{number:02d}-{slugify(title)}"
            current_section = {
                "id": category_id,
                "numero": number,
                "titulo": title,
                "title": title,
            }
            categories[category_id] = {
                "id": category_id,
                "numero": number,
                "titulo": title,
                "total_restaurantes": 0,
                "chunk": f"chunks/by_category/{category_id}.md",
            }
            continue

        if line.startswith("## "):
            flush_entry()
            active_restaurant_section = False
            current_section = None
            continue

        if not active_restaurant_section or current_section is None:
            continue

        entry_match = ENTRY_RE.match(line)
        if entry_match:
            flush_entry()
            current_entry = {
                "name": entry_match.group("name").strip(),
                "lines": [line],
                "fields": {},
            }
            continue

        if current_entry is None:
            continue

        current_entry["lines"].append(line)
        field_match = FIELD_RE.match(line)
        if field_match:
            key = normalize_key(field_match.group("key"))
            value = field_match.group("value").strip()
            if value:
                current_entry["fields"][key] = value

    flush_entry()
    assign_ids(entries)
    assign_keywords(entries)

    ordered_categories = sorted(categories.values(), key=lambda item: item["numero"])
    return entries, ordered_categories


def write_knowledge_base(
    *,
    source: Path,
    output_dir: Path,
    entries: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    category_dir = output_dir / "chunks" / "by_category"
    restaurant_dir = output_dir / "chunks" / "by_restaurant"
    category_dir.mkdir(parents=True, exist_ok=True)
    restaurant_dir.mkdir(parents=True, exist_ok=True)
    clean_generated_files(output_dir=output_dir)

    source_text = source.read_text(encoding="utf-8")
    (output_dir / "source.md").write_text(source_text, encoding="utf-8")

    entries_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, entry in enumerate(entries, start=1):
        restaurant_chunk = f"chunks/by_restaurant/{index:03d}-{entry['id']}.md"
        entry["fonte_chunk"] = restaurant_chunk
        entries_by_category[entry["categoria_id"]].append(entry)
        (output_dir / restaurant_chunk).write_text(
            build_restaurant_chunk(entry),
            encoding="utf-8",
        )

    for category in categories:
        category_entries = entries_by_category.get(category["id"], [])
        (output_dir / category["chunk"]).write_text(
            build_category_chunk(category, category_entries),
            encoding="utf-8",
        )

    index = {
        "versao": "sao-paulo-v2",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fonte": "source.md",
        "cidade": "São Paulo",
        "total_restaurantes": len(entries),
        "categorias": categories,
        "restaurantes": entries,
    }
    (output_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_generated_files(*, output_dir: Path) -> None:
    for filename in ("index.json", "source.md"):
        target = output_dir / filename
        if target.exists():
            target.unlink()

    for folder in (
        output_dir / "chunks" / "by_category",
        output_dir / "chunks" / "by_restaurant",
    ):
        if not folder.exists():
            continue
        for path in folder.glob("*.md"):
            path.unlink()


def build_restaurant_chunk(entry: dict[str, Any]) -> str:
    lines = [
        f"# {entry['nome']}",
        "",
        f"- **ID:** {entry['id']}",
        f"- **Categoria RAG:** {entry['categoria']}",
        f"- **Cidade:** {entry['cidade']}",
    ]
    if entry.get("bairro"):
        lines.append(f"- **Bairro:** {entry['bairro']}")
    lines.extend(["", entry["markdown"].strip(), ""])
    return "\n".join(lines)


def build_category_chunk(
    category: dict[str, Any],
    entries: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {category['titulo']}",
        "",
        f"- **Categoria ID:** {category['id']}",
        f"- **Total de restaurantes:** {len(entries)}",
        "- **Cidade:** São Paulo",
        "",
    ]
    for entry in entries:
        lines.append(entry["markdown"].strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def assign_ids(entries: list[dict[str, Any]]) -> None:
    seen: dict[str, int] = {}
    for entry in entries:
        base = slugify(entry["nome"]) or "restaurante"
        count = seen.get(base, 0) + 1
        seen[base] = count
        entry["id"] = base if count == 1 else f"{base}-{count}"


def assign_keywords(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        raw = " ".join(
            str(part)
            for part in [
                entry.get("nome"),
                entry.get("categoria"),
                entry.get("tipo"),
                entry.get("bairro"),
                entry.get("cidade"),
                entry.get("distincao"),
                entry.get("descricao"),
            ]
            if part
        )
        entry["termos_busca"] = sorted(set(tokenize(raw)))[:80]


def extract_neighborhood(address: str | None) -> str | None:
    if not address:
        return None

    value = address.strip()
    for separator in ("—", " - "):
        if separator in value:
            value = value.rsplit(separator, 1)[-1].strip()
            break
    else:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) >= 2:
            value = parts[-1]
        else:
            return None

    value = re.sub(r"\([^)]*\)", "", value).strip()
    if "," in value:
        value = value.split(",", 1)[0].strip()
    return value or None


def normalize_key(value: str) -> str:
    normalized = strip_accents(value).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def slugify(value: str) -> str:
    normalized = strip_accents(value).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def tokenize(value: str) -> list[str]:
    normalized = strip_accents(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return [
        token
        for token in normalized.split()
        if len(token) >= 3 and token not in STOPWORDS
    ]


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


STOPWORDS = {
    "com",
    "das",
    "dos",
    "para",
    "por",
    "que",
    "sao",
    "sua",
    "sul",
    "uma",
    "uns",
    "nas",
    "nos",
    "rua",
    "avenida",
    "restaurante",
    "restaurantes",
    "cozinha",
    "cozinhas",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera index e chunks RAG a partir da base Markdown de restaurantes.",
    )
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("app/data/restaurant_knowledge/sao_paulo"),
    )
    args = parser.parse_args()

    entries, categories = parse_markdown(args.source)
    write_knowledge_base(
        source=args.source,
        output_dir=args.output_dir,
        entries=entries,
        categories=categories,
    )
    print(
        f"Generated {len(entries)} restaurants across {len(categories)} categories in {args.output_dir}",
    )


if __name__ == "__main__":
    main()
