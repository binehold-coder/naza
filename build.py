from __future__ import annotations

import json
import re
import shutil
from html import escape
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
OUTPUT = ROOT / "preview-site"

# Directories used only for development/building, never part of the public site.
EXCLUDED_DIRS = {
    ".git", ".github", ".vercel", ".venv", "venv", "node_modules",
    "__pycache__", "preview-site", "app", "content", "templates",
}
EXCLUDED_FILES = {
    "build.py", "requirements.txt", "README.txt", "README.md",
    "NAZA_TECHNICAL_AUDIT.md",
}
STATIC_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".xml", ".txt",
    ".webmanifest", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".avif", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
}

WEEKDAYS = {
    "fr": [
        ("monday", "Lundi"), ("tuesday", "Mardi"), ("wednesday", "Mercredi"),
        ("thursday", "Jeudi"), ("friday", "Vendredi"), ("saturday", "Samedi"),
        ("sunday", "Dimanche"),
    ],
    "uk": [
        ("monday", "Понеділок"), ("tuesday", "Вівторок"), ("wednesday", "Середа"),
        ("thursday", "Четвер"), ("friday", "П'ятниця"), ("saturday", "Субота"),
        ("sunday", "Неділя"),
    ],
}

SEO = {
    "fr": {
        "title": "Naza Couture - Atelier de Couture au Bourget-du-Lac",
        "description": "Naza Couture — Atelier de couture au Bourget-du-Lac. Couture sur mesure, retouches de vêtements et création d'accessoires uniques.",
        "locale": "fr_FR",
    },
    "uk": {
        "title": "Головна - Naza Couture | Ательє у Le Bourget-du-Lac",
        "description": "Naza Couture — Професійне ательє у Le Bourget-du-Lac. Індивідуальне пошиття, якісний ремонт одягу та підгон по фігурі.",
        "locale": "uk_UA",
    },
}


def load_json(name: str):
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def validate(data, schema_name: str):
    schema = load_json(schema_name)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path)))
    if errors:
        details = "\n".join(
            f"- {'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}"
            for err in errors
        )
        raise SystemExit(f"Validation failed for {schema_name}:\n{details}")


def copy_public_site():
    """Copy the existing static website while excluding source/build internals."""
    OUTPUT.mkdir(parents=True, exist_ok=True)

    for item in ROOT.iterdir():
        if item.is_dir():
            if item.name in EXCLUDED_DIRS or item.name.startswith("."):
                continue
            shutil.copytree(item, OUTPUT / item.name, ignore=shutil.ignore_patterns(
                ".git", ".DS_Store", "__pycache__", "*.pyc", "node_modules", "venv", ".venv"
            ))
        elif item.is_file():
            if item.name in EXCLUDED_FILES:
                continue
            if item.name.startswith(".") and item.name != ".nojekyll":
                continue
            if item.suffix.lower() in STATIC_EXTENSIONS or item.name == ".nojekyll":
                shutil.copy2(item, OUTPUT / item.name)


def format_hour(value: str) -> str:
    return f"{int(value[:2])}h{value[3:]}"


def schedule_rows(site: dict, lang: str, paragraph_class: str) -> str:
    rows = []
    for day_key, label in WEEKDAYS[lang]:
        hours = site["opening_hours"].get(day_key)
        if hours:
            rows.append(
                f'<p class="{escape(paragraph_class, quote=True)}">'
                f'{escape(label)} {format_hour(hours["open"])}-{format_hour(hours["close"])}'
                "</p>"
            )
    return "\n".join(rows)


def update_contact_schedule(path: Path, site: dict, lang: str):
    if not path.is_file():
        raise SystemExit(f"Required contact page is missing: {path.relative_to(OUTPUT)}")

    html = path.read_text(encoding="utf-8")
    heading = r"Horaires d'ouverture" if lang == "fr" else r"Графік роботи"
    pattern = re.compile(
        rf'(?P<heading><h4\b[^>]*>\s*{heading}\s*</h4>)'
        rf'(?P<gap>\s*)'
        rf'(?P<rows>(?:<p\b[^>]*>.*?</p>\s*)+)',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        raise SystemExit(
            f"Could not locate the schedule block in {path.relative_to(OUTPUT)}; "
            "build stopped to avoid publishing stale hours."
        )

    first_open_tag = re.match(r"<p\b([^>]*)>", match.group("rows"), re.IGNORECASE)
    attrs = first_open_tag.group(1) if first_open_tag else ""
    class_match = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', attrs, re.IGNORECASE | re.DOTALL)
    paragraph_class = class_match.group(2) if class_match else ""
    new_rows = schedule_rows(site, lang, paragraph_class)
    replacement = match.group("heading") + match.group("gap") + new_rows
    updated = html[:match.start()] + replacement + html[match.end():]
    path.write_text(updated, encoding="utf-8")


def main():
    site = load_json("site.json")
    validate(site, "site.schema.json")

    exceptions = load_json("exceptions.json")
    validate(exceptions, "exceptions.schema.json")

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["hour"] = format_hour

    # Rebuild the deployable folder from the full static site on every run.
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    copy_public_site()

    for lang in ("fr", "uk"):
        is_ua = lang == "uk"
        page_dir = OUTPUT / ("ua" if is_ua else "")
        page_dir.mkdir(parents=True, exist_ok=True)
        asset_prefix = "../" if is_ua else ""
        context = {
            "site": site,
            "lang": lang,
            "is_ua": is_ua,
            "asset_prefix": asset_prefix,
            "page_prefix": "../" if is_ua else "",
            "canonical": site["public_url"] + ("ua/" if is_ua else ""),
            "seo": SEO[lang],
            "weekdays": WEEKDAYS[lang],
            "exceptions": exceptions["exceptions"],
        }
        html = env.get_template("pages/home.html").render(**context)
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    # Contact pages are retained from the original site, but their hours come
    # from the same JSON source as the generated homepages.
    update_contact_schedule(OUTPUT / "contact.html", site, "fr")
    update_contact_schedule(OUTPUT / "ua" / "contact.html", site, "uk")

    print("Build successful: complete FR/UA site copied to ./preview-site.")
    print("Generated homepages and synchronized all four schedule blocks from content/site.json.")
    print("Original source HTML files were not modified.")


if __name__ == "__main__":
    main()
