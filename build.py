from __future__ import annotations

import json
import shutil
from datetime import date, time
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
OUTPUT = ROOT / "preview-site"


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


def validate_time_range(hours: dict, location: str):
    opening = time.fromisoformat(hours["open"])
    closing = time.fromisoformat(hours["close"])
    if opening >= closing:
        raise SystemExit(
            f"Schedule validation failed: {location}: opening time must be earlier than closing time"
        )


def validate_schedule(site: dict, exceptions: dict):
    for day, hours in site["opening_hours"].items():
        if isinstance(hours, dict) and "open" in hours and "close" in hours:
            validate_time_range(hours, f"opening_hours/{day}")

    items = exceptions["exceptions"]
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise SystemExit("Schedule validation failed: exception IDs must be unique")

    parsed = []
    for item in items:
        try:
            start = date.fromisoformat(item["start_date"])
            end = date.fromisoformat(item["end_date"])
        except ValueError as exc:
            raise SystemExit(
                f"Schedule validation failed: invalid date in exception '{item['id']}'"
            ) from exc

        if start > end:
            raise SystemExit(
                f"Schedule validation failed: start_date is after end_date in '{item['id']}'"
            )

        if item["type"] == "hours":
            validate_time_range(item["hours"], f"exceptions/{item['id']}/hours")

        parsed.append((item["id"], start, end))

    # Overlap is permitted only when a one-day exception overrides a longer range.
    for index, (left_id, left_start, left_end) in enumerate(parsed):
        for right_id, right_start, right_end in parsed[index + 1:]:
            overlaps = left_start <= right_end and right_start <= left_end
            if not overlaps:
                continue

            left_is_single = left_start == left_end
            right_is_single = right_start == right_end
            valid_override = left_is_single != right_is_single
            if not valid_override:
                raise SystemExit(
                    "Schedule validation failed: conflicting exceptions "
                    f"'{left_id}' and '{right_id}' overlap. Only a one-day exception "
                    "may override a multi-day range."
                )


def main():
    site = load_json("site.json")
    validate(site, "site.schema.json")

    exceptions = load_json("exceptions.json")
    validate(exceptions, "exceptions.schema.json")
    validate_schedule(site, exceptions)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["hour"] = lambda value: f"{int(value[:2])}h{value[3:]}"

    # Labels are transcribed from the existing pages; unknown Sunday status remains unknown.
    weekdays = {
        "fr": [("monday", "Lundi"), ("tuesday", "Mardi"), ("wednesday", "Mercredi"),
               ("thursday", "Jeudi"), ("friday", "Vendredi"), ("saturday", "Samedi"), ("sunday", "Dimanche")],
        "uk": [("monday", "Понеділок"), ("tuesday", "Вівторок"), ("wednesday", "Середа"),
               ("thursday", "Четвер"), ("friday", "П'ятниця"), ("saturday", "Субота"), ("sunday", "Неділя")],
    }
    seo = {
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

    # Keep generated output separate from source HTML. Never overwrite the originals.
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

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
            "seo": seo[lang],
            "weekdays": weekdays[lang],
            # Labels remain in the validated source data for future bot management,
            # but are intentionally not published on the website.
            "exceptions": [
                {key: value for key, value in item.items() if key != "label"}
                for item in exceptions["exceptions"]
            ],
        }
        html = env.get_template("pages/home.html").render(**context)
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    # Copy existing static resources without modifying them.
    for directory in ("css", "js", "assets"):
        source = ROOT / directory
        if source.exists():
            shutil.copytree(source, OUTPUT / directory)

    print("Build successful: FR and UA homepages generated in ./preview-site")
    print("Original HTML files were not modified.")


if __name__ == "__main__":
    main()
