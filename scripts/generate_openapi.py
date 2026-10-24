"""Genera una especificación OpenAPI por deporte desde ``app.main:app``.

Uso:
    .\\.venv\\Scripts\\python.exe scripts\\generate_openapi.py
    .\\.venv\\Scripts\\python.exe scripts\\generate_openapi.py --check

Cada archivo contiene solo las rutas de su deporte y los esquemas que esas
rutas referencian, de modo que cada contrato es autocontenido.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "openapi"

SERVERS = [
    {"url": "http://127.0.0.1:8000", "description": "Desarrollo local (uvicorn)"},
    {"url": "http://localhost:8000", "description": "Alias de loopback"},
]

TAGS = {
    "System": "Salud del servicio y catálogo de deportes soportados.",
    "Records": "Registro manual de partidos y picks del analista.",
    "Football": "Resultados y liquidación de fútbol.",
    "Football Rankings": "Rankings de fútbol enviados y versionados por analistas.",
    "NBA": "Resultados y liquidación de básquetbol (NBA).",
    "Baseball": "Estadísticas, resultados y liquidación de béisbol (MLB/KBO).",
    "Tennis": "Conteo de partidos, resultados y liquidación de tenis (ATP/WTA).",
    "Prompts": "Prompts de análisis y evaluación versionados por deporte.",
}

TARGETS: list[dict[str, Any]] = [
    {
        "file": "system.yaml",
        "title": "BET Analytics API - Sistema",
        "sport": "sistema",
        "prefixes": ["/health", "/api/v1/sports", "/api/v1/records"],
    },
    {
        "file": "football.yaml",
        "title": "BET Analytics API - Fútbol",
        "sport": "fútbol",
        "prefixes": ["/api/v1/football"],
        "extra_servers": [
            {
                "url": "https://start-bet-api-rest.xzpbpr.easypanel.host",
                "description": "Desarrollo",
            }
        ],
    },
    {
        "file": "nba.yaml",
        "title": "BET Analytics API - NBA",
        "sport": "básquetbol (NBA)",
        "prefixes": ["/api/v1/nba"],
    },
    {
        "file": "baseball.yaml",
        "title": "BET Analytics API - Béisbol",
        "sport": "béisbol (MLB/KBO)",
        "prefixes": ["/api/v1/baseball"],
    },
    {
        "file": "tennis.yaml",
        "title": "BET Analytics API - Tenis",
        "sport": "tenis (ATP/WTA)",
        "prefixes": ["/api/v1/tennis"],
    },
    {
        "file": "prompts.yaml",
        "title": "BET Analytics API - Prompts",
        "sport": "prompts de analistas",
        "prefixes": ["/api/v1/prompts"],
        "extra_servers": [
            {
                "url": "https://start-bet-api-rest.xzpbpr.easypanel.host",
                "description": "API desplegada",
            }
        ],
    },
]


def build_base_spec() -> dict[str, Any]:
    """Devuelve el contrato completo con metadatos comunes."""
    spec = app.openapi()
    spec["info"] = {
        "title": "BET Analytics API",
        "description": (
            "API REST para registrar, consultar y liquidar apuestas deportivas. "
            "El registro es manual: la API no calcula probabilidades."
        ),
        "version": spec["info"]["version"],
        "contact": {"name": "BET Analytics"},
        "license": {"name": "Privado"},
    }
    spec["servers"] = [dict(server) for server in SERVERS]
    base_url = get_settings().public_base_url.strip()
    if base_url:
        spec["servers"].append(
            {
                "url": base_url.rstrip("/"),
                "description": "Instancia pública (PUBLIC_BASE_URL)",
            }
        )
    spec["tags"] = [{"name": name, "description": desc} for name, desc in TAGS.items()]
    return spec


def path_matches(path: str, prefixes: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def iter_refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref
        for value in node.values():
            yield from iter_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_refs(value)


def used_component_refs(paths: dict[str, Any], components: dict[str, Any]) -> set[str]:
    """Cierra transitivamente las referencias a ``#/components/...``."""
    seen: set[str] = set()
    pending = list(iter_refs(paths))
    while pending:
        ref = pending.pop()
        if ref in seen or not ref.startswith("#/components/"):
            continue
        seen.add(ref)
        parts = ref.split("/")
        if len(parts) < 4:
            continue
        node = components.get(parts[2], {}).get(parts[3])
        if node is not None:
            pending.extend(iter_refs(node))
    return seen


def prune_components(
    paths: dict[str, Any], components: dict[str, Any]
) -> dict[str, Any]:
    refs = used_component_refs(paths, components)
    pruned: dict[str, Any] = {}
    for section, items in components.items():
        kept = {
            name: value
            for name, value in items.items()
            if f"#/components/{section}/{name}" in refs
        }
        if kept:
            pruned[section] = kept
    return pruned


def build_sport_spec(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    prefixes = target["prefixes"]
    paths = {
        path: item
        for path, item in base["paths"].items()
        if path_matches(path, prefixes)
    }
    components = prune_components(paths, base.get("components", {}))

    used_tags = {
        tag
        for item in paths.values()
        for operation in item.values()
        if isinstance(operation, dict)
        for tag in operation.get("tags", [])
    }

    spec: dict[str, Any] = {
        "openapi": base["openapi"],
        "info": {
            "title": target["title"],
            "description": (
                f"Contrato OpenAPI de {target['sport']}. Incluye solo las rutas "
                f"{', '.join(f'`{prefix}`' for prefix in prefixes)} y los esquemas "
                "que esas rutas referencian. El resto de deportes está en archivos "
                "separados dentro de `openapi/`."
            ),
            "version": base["info"]["version"],
            "contact": base["info"]["contact"],
            "license": base["info"]["license"],
        },
        "paths": paths,
    }
    if components:
        spec["components"] = components
    spec["servers"] = [
        *base["servers"],
        *target.get("extra_servers", []),
    ]
    spec["tags"] = [tag for tag in base["tags"] if tag["name"] in used_tags]
    return spec


def dump_yaml(spec: dict[str, Any]) -> str:
    return yaml.safe_dump(
        spec,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Directorio de salida (por defecto: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo verifica que los archivos estén al día; no escribe.",
    )
    args = parser.parse_args()

    base = build_base_spec()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    stale: list[Path] = []
    for target in TARGETS:
        spec = build_sport_spec(base, target)
        text = dump_yaml(spec)
        destination = out_dir / target["file"]
        operations = sum(
            1
            for item in spec["paths"].values()
            for method in item
            if method in {"get", "post", "put", "patch", "delete"}
        )
        schemas = len(spec.get("components", {}).get("schemas", {}))

        if args.check:
            current = (
                destination.read_text(encoding="utf-8")
                if destination.exists()
                else ""
            )
            status = "ok" if current == text else "desactualizado"
            if current != text:
                stale.append(destination)
        else:
            destination.write_text(text, encoding="utf-8")
            status = "escrito"

        print(
            f"{destination.relative_to(ROOT) if destination.is_relative_to(ROOT) else destination}"
            f"  rutas={len(spec['paths'])}  operaciones={operations}"
            f"  esquemas={schemas}  {status}"
        )

    if args.check:
        if stale:
            print("\nArchivos desactualizados. Ejecuta el generador sin --check.")
            return 1
        print("\nTodos los contratos están al día.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
