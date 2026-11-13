from __future__ import annotations

import json
import re
import shutil
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from markupsafe import Markup
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
    "NAZA_TECHNICAL_AUDIT.md", "vercel.json",
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


def day_sep(lang: str) -> str:
    """Separator after a weekday name: French typography puts a no-break space before the colon."""
    return "&nbsp;:" if lang == "fr" else ":"


def schedule_rows(site: dict, lang: str, paragraph_class: str) -> str:
    rows = []
    for day_key, label in WEEKDAYS[lang]:
        hours = site["opening_hours"].get(day_key)
        if hours is None:
            # Not specified: do not display the day at all.
            continue
        if hours.get("closed"):
            text = f'{escape(label)}{day_sep(lang)} {"Fermé" if lang == "fr" else "Зачинено"}'
        else:
            text = f'{escape(label)}{day_sep(lang)} {format_hour(hours["open"])}-{format_hour(hours["close"])}'
        rows.append(
            f'<p class="{escape(paragraph_class, quote=True)}">{text}</p>'
        )
    return "\n".join(rows)


def update_contact_schedule(path: Path, site: dict, lang: str, exceptions: list):
    if not path.is_file():
        raise SystemExit(f"Required contact page is missing: {path.relative_to(OUTPUT)}")

    html = path.read_text(encoding="utf-8")
    heading = r"Horaires d'ouverture" if lang == "fr" else r"Графік роботи"
    pattern = re.compile(
        rf'(?P<heading><h4\b[^>]*>\s*{heading}\s*</h4>)'
        rf'(?P<gap>\s*)'
        rf'(?P<rows>(?:<p\b[^>]*>.*?</p>\s*)+)'
        # A previously generated exceptions notice may already follow the rows
        # in the source HTML; consume it so it is replaced, not duplicated.
        rf'(?P<notice><div\b[^>]*\bid="schedule-exceptions-\w+"[^>]*>\s*</div>(?:\s*<script>.*?</script>)?)?',
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
    replacement = (match.group("heading") + match.group("gap") + new_rows
                   + "\n" + exception_notice_markup(lang))
    updated = html[:match.start()] + replacement + html[match.end():]
    path.write_text(updated, encoding="utf-8")




def validate_exceptions_semantics(data: dict):
    """Validate cross-field rules that JSON Schema cannot express reliably."""
    records = data.get("exceptions", [])
    seen_ids = set()
    parsed = []

    for index, item in enumerate(records):
        prefix = f"exceptions/{index}"
        exception_id = item["id"]
        if exception_id in seen_ids:
            raise SystemExit(f"Validation failed for exceptions.json: duplicate id '{exception_id}'.")
        seen_ids.add(exception_id)

        try:
            start = date.fromisoformat(item["start_date"])
            end = date.fromisoformat(item["end_date"])
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Validation failed for {prefix}: dates must be real ISO dates (YYYY-MM-DD).") from exc

        if end < start:
            raise SystemExit(f"Validation failed for {prefix}: end_date must not be earlier than start_date.")

        if item["type"] == "hours":
            opening = item["hours"]["open"]
            closing = item["hours"]["close"]
            if opening >= closing:
                raise SystemExit(f"Validation failed for {prefix}: closing time must be later than opening time.")

        parsed.append((start, end, exception_id))

    parsed.sort(key=lambda row: (row[0], row[1], row[2]))
    for previous, current in zip(parsed, parsed[1:]):
        _, previous_end, previous_id = previous
        current_start, _, current_id = current
        if current_start <= previous_end:
            raise SystemExit(
                "Validation failed for exceptions.json: "
                f"exceptions '{previous_id}' and '{current_id}' overlap. "
                "Overlapping date ranges are not allowed."
            )


PRICE_WORDS = {
    "fr": {"from": "à partir de", "on_request": "sur demande"},
    "uk": {"from": "від", "on_request": "за запитом"},
}


def format_amount(value) -> str:
    """12 -> "12", 12.5 -> "12,50" (both languages use a decimal comma)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".replace(".", ",")


def format_price(price: dict, lang: str) -> str:
    """Price cell text. Keep in sync with naza-bot app/services/services_service.py."""
    words = PRICE_WORDS[lang]
    kind = price["type"]
    if kind == "fixed":
        text = f"{format_amount(price['amount'])} €"
    elif kind == "from":
        text = f"{words['from']} {format_amount(price['amount'])} €"
    elif kind == "range":
        text = f"{format_amount(price['min'])}-{format_amount(price['max'])} €"
    elif kind == "list":
        text = " / ".join(f"{format_amount(a)} €" for a in price["amounts"])
    else:
        text = words["on_request"]
    note = price.get("note")
    if note:
        text += f" {note[lang]}"
    return text


def validate_services_semantics(data: dict):
    """Rules JSON Schema cannot express. Mirrored in naza-bot services_service.check_services()."""
    seen = set()

    def unique(item_id, where):
        if item_id in seen:
            raise SystemExit(f"Validation failed for services.json: duplicate id '{item_id}' ({where}).")
        seen.add(item_id)

    def amount_ok(value):
        return round(value * 100) == value * 100

    for c_index, category in enumerate(data["categories"]):
        unique(category["id"], f"categories/{c_index}")
        for i_index, item in enumerate(category["items"]):
            where = f"categories/{c_index}/items/{i_index}"
            unique(item["id"], where)
            price = item["price"]
            amounts = [price[k] for k in ("amount", "min", "max") if k in price] + price.get("amounts", [])
            if not all(amount_ok(a) for a in amounts):
                raise SystemExit(f"Validation failed for {where}: prices may have at most 2 decimals.")
            if price["type"] == "range" and price["min"] >= price["max"]:
                raise SystemExit(f"Validation failed for {where}: range minimum must be lower than maximum.")
    for u_index, row in enumerate(data["urgency"]):
        unique(row["id"], f"urgency/{u_index}")


def visible_categories(data: dict) -> list:
    """Visible categories with their visible services; categories left empty are not shown."""
    result = []
    for category in data["categories"]:
        if not category["visible"]:
            continue
        items = [item for item in category["items"] if item["visible"]]
        if items:
            result.append({**category, "items": items})
    return result


def replace_marked_block(path: Path, name: str, rendered: str):
    """Replace the content between every <!-- name:start ... --> and <!-- name:end --> pair with ``rendered``."""
    if not path.is_file():
        raise SystemExit(f"Required page is missing: {path.relative_to(OUTPUT)}")
    html = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(?P<start><!-- {re.escape(name)}:start[^>]*-->)(?P<body>.*?)(?P<indent>[ \t]*)(?P<end><!-- {re.escape(name)}:end -->)",
        re.DOTALL,
    )
    count = 0

    def replace(match):
        nonlocal count
        count += 1
        indent = match.group("indent")
        body = "\n".join((indent + line) if line.strip() else "" for line in rendered.strip("\n").split("\n"))
        return match.group("start") + "\n" + body + "\n" + indent + match.group("end")

    # Every block with this name on the page is replaced (e.g. social links in the body and the footer).
    html = pattern.sub(replace, html)
    if not count:
        raise SystemExit(f"Could not locate the {name} block in {path.relative_to(OUTPUT)}; build stopped.")
    path.write_text(html, encoding="utf-8")


def update_services_page(path: Path, env: Environment, services: dict, lang: str):
    """Replace the block between the services markers with tables generated from JSON."""
    rendered = env.get_template("partials/services_tables.html").render(
        lang=lang, categories=visible_categories(services), urgency=services["urgency"],
    )
    replace_marked_block(path, "services", rendered)


# ---------- contacts ----------

# Order on the site; key -> (label, Font Awesome icon, allowed hosts). Mirrored in the bot.
SOCIAL_NETWORKS = {
    "instagram": ("Instagram", "fa-instagram", ("instagram.com", "www.instagram.com")),
    "facebook": ("Facebook", "fa-facebook-f", ("facebook.com", "www.facebook.com", "m.facebook.com")),
    "tiktok": ("TikTok", "fa-tiktok", ("tiktok.com", "www.tiktok.com")),
}
# Pages whose contact data come from site.json (generated home pages use the templates directly).
SOCIAL_PAGES = ("about", "contact", "legal", "portfolio", "services",
                "ua/about", "ua/contact", "ua/portfolio", "ua/services")


def validate_contact_semantics(site: dict):
    contact = site["contact"]
    phone = contact["phone_e164"]
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise SystemExit(f"contact.phone_e164 is not an international number: {phone}")
    display_digits = re.sub(r"\D", "", contact["phone_display"])
    if display_digits.startswith("0"):  # French national format: 07 68 00 41 97 = +33 7 68 00 41 97
        display_digits = "33" + display_digits[1:]
    if display_digits != phone[1:]:
        raise SystemExit("contact.phone_display does not match contact.phone_e164")
    social = contact["social"]
    if not social:
        raise SystemExit("contact.social: at least one social network is required")
    for key, url in social.items():
        if key not in SOCIAL_NETWORKS:
            raise SystemExit(f"contact.social.{key}: unknown network")
        host = urlsplit(url).hostname or ""
        if urlsplit(url).scheme != "https" or host not in SOCIAL_NETWORKS[key][2]:
            raise SystemExit(f"contact.social.{key}: URL must be https://{SOCIAL_NETWORKS[key][2][0]}/...")


def social_links(site: dict) -> list:
    social = site["contact"]["social"]
    return [
        {"url": social[key], "label": label, "icon": icon}
        for key, (label, icon, _) in SOCIAL_NETWORKS.items() if social.get(key)
    ]


def update_contact_blocks(env: Environment, site: dict):
    """Social links on every copied page, phone/email on the contact and legal pages."""
    for rel in SOCIAL_PAGES:
        replace_marked_block(OUTPUT / f"{rel}.html", "social-links",
                             env.get_template("partials/social_links.html").render())
    for rel, lang in (("contact", "fr"), ("ua/contact", "uk")):
        replace_marked_block(OUTPUT / f"{rel}.html", "contact-details",
                             env.get_template("partials/contact_details.html").render(site=site, lang=lang))
    replace_marked_block(OUTPUT / "legal.html", "legal-contact",
                         env.get_template("partials/legal_contact.html").render(site=site))


# ---------- portfolio ----------

PORTFOLIO_SOURCE = CONTENT / "portfolio"     # images uploaded by the bot live next to the JSON
PORTFOLIO_OUTPUT = "assets/img/portfolio/"   # where the site serves them


def validate_portfolio_semantics(data: dict):
    """Rules JSON Schema cannot express; mirrored in the bot (portfolio_service.check_portfolio)."""
    ids, files = set(), set()
    for item in data["items"]:
        if item["id"] in ids:
            raise SystemExit(f"Portfolio: duplicate id {item['id']}")
        ids.add(item["id"])
        name = item["image"]["file"]
        if name in files:
            raise SystemExit(f"Portfolio: image {name} is used twice")
        files.add(name)
        if not (PORTFOLIO_SOURCE / name).is_file():
            raise SystemExit(f"Portfolio: image content/portfolio/{name} is missing")


def visible_portfolio(data: dict) -> list:
    return [item for item in data["items"] if item["visible"]]


def build_portfolio(env: Environment, portfolio: dict):
    """Copy the visible images into the site and generate the grid + modals of both pages."""
    items = visible_portfolio(portfolio)
    target = OUTPUT / PORTFOLIO_OUTPUT
    target.mkdir(parents=True, exist_ok=True)
    for item in items:
        shutil.copy2(PORTFOLIO_SOURCE / item["image"]["file"], target / item["image"]["file"])
    for lang, page in (("fr", OUTPUT / "portfolio.html"), ("uk", OUTPUT / "ua" / "portfolio.html")):
        context = {"lang": lang, "items": items, "asset_prefix": "../" if lang == "uk" else "",
                   "image_dir": PORTFOLIO_OUTPUT}
        replace_marked_block(page, "portfolio", env.get_template("partials/portfolio_cards.html").render(**context))
        replace_marked_block(page, "portfolio-modals",
                             env.get_template("partials/portfolio_modals.html").render(**context))


def load_announcement():
    """The single announcement (content/announcements.json), or None.

    The file is optional so that content branches created before stage 8 still build.
    """
    if not (CONTENT / "announcements.json").exists():
        return None
    data = load_json("announcements.json")
    validate(data, "announcements.schema.json")
    item = data["announcement"]
    if item is None:
        return None
    if item["end_date"] is not None and item["end_date"] < item["start_date"]:
        raise SystemExit("Validation failed for announcements.json: end_date is before start_date.")
    details = item["details"]
    if (details["fr"] is None) != (details["uk"] is None):
        raise SystemExit("Validation failed for announcements.json: details must be set in both languages or in none.")
    for lang in ("fr", "uk"):
        if not item["text"][lang].strip() or "\n" in item["text"][lang]:
            raise SystemExit(f"Validation failed for announcements.json: text/{lang} must be one non-empty line.")
    return item


def announcement_for(item, lang: str):
    """Language-specific announcement data embedded in the pages (shown by date in js/exceptions.js)."""
    if item is None:
        return None
    return {"start_date": item["start_date"], "end_date": item["end_date"],
            "text": item["text"][lang], "details": item["details"][lang]}


def exception_notice_markup(lang: str) -> str:
    """Container for the exceptions notice under the opening hours; filled by js/exceptions.js."""
    return (f'<div id="schedule-exceptions-{lang}" class="mt-3 text-warning" '
            'data-exceptions-notice aria-live="polite" hidden></div>')


def inject_exceptions_runtime(path: Path, lang: str, asset_prefix: str, exceptions: list, announcement=None):
    """Add the top banner and the exceptions/announcement data + script to one page."""
    html = path.read_text(encoding="utf-8")
    payload = json.dumps({"lang": lang, "items": exceptions, "announcement": announcement_for(announcement, lang)},
                         ensure_ascii=False).replace("<", "\\u003c")
    banner = '<div id="exceptions-banner" class="exceptions-banner" role="status" hidden></div>'
    runtime = (f'<script>window.NAZA_EXCEPTIONS = {payload};</script>\n'
               f'<script src="{asset_prefix}js/exceptions.js"></script>\n')
    html, body_count = re.subn(r"(<body\b[^>]*>)", lambda m: m.group(1) + "\n" + banner, html, count=1)
    html, end_count = re.subn(r"(</body>)", lambda m: runtime + m.group(1), html, count=1)
    if body_count != 1 or end_count != 1:
        raise SystemExit(f"Could not add the exceptions banner to {path.relative_to(OUTPUT)}.")
    path.write_text(html, encoding="utf-8")


def inject_exceptions_everywhere(exceptions: list, announcement=None):
    """Every page with the main navbar gets the banner (FR in the root, UA in ua/)."""
    for path in sorted(OUTPUT.rglob("*.html")):
        relative = path.relative_to(OUTPUT)
        html = path.read_text(encoding="utf-8")
        if 'id="mainNav"' not in html:
            continue
        is_ua = relative.parts[0] == "ua"
        inject_exceptions_runtime(path, "uk" if is_ua else "fr", "../" if is_ua else "", exceptions, announcement)


def main():
    site = load_json("site.json")
    validate(site, "site.schema.json")
    validate_contact_semantics(site)

    exceptions = load_json("exceptions.json")
    validate(exceptions, "exceptions.schema.json")
    validate_exceptions_semantics(exceptions)

    announcement = load_announcement()

    services = load_json("services.json")
    validate(services, "services.schema.json")
    validate_services_semantics(services)

    portfolio = load_json("portfolio.json")
    validate(portfolio, "portfolio.schema.json")
    validate_portfolio_semantics(portfolio)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["hour"] = format_hour
    env.filters["price"] = format_price
    env.globals["day_sep"] = lambda lang: Markup(day_sep(lang))
    env.globals["social_links"] = social_links(site)

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
            # UA pages live in ua/ and link to their UA siblings.
            "page_prefix": "",
            "canonical": site["public_url"] + ("ua/" if is_ua else ""),
            "seo": SEO[lang],
            "weekdays": WEEKDAYS[lang],
            "exceptions": exceptions["exceptions"],
            "exception_notice": exception_notice_markup(lang),
        }
        html = env.get_template("pages/home.html").render(**context)
        (page_dir / "index.html").write_text(html, encoding="utf-8")

    # Contact pages are retained from the original site, but their hours come
    # from the same JSON source as the generated homepages.
    update_contact_schedule(OUTPUT / "contact.html", site, "fr", exceptions["exceptions"])
    update_contact_schedule(OUTPUT / "ua" / "contact.html", site, "uk", exceptions["exceptions"])

    # Price tables of the services pages come from content/services.json.
    update_services_page(OUTPUT / "services.html", env, services, "fr")
    update_services_page(OUTPUT / "ua" / "services.html", env, services, "uk")

    # Portfolio grid and modals come from content/portfolio.json (+ images in content/portfolio/).
    build_portfolio(env, portfolio)

    # Phone, email and social links come from content/site.json (contact).
    update_contact_blocks(env, site)

    # Banner + notice + announcement data on every page; the script shows items by date.
    inject_exceptions_everywhere(exceptions["exceptions"], announcement)

    print("Build successful: complete FR/UA site copied to ./preview-site.")
    print("Generated FR/UA homepages, synchronized contact schedules, added exception notices and banners.")
    print("Original source HTML files were not modified.")


if __name__ == "__main__":
    main()
