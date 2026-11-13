// Schedule exceptions (vacation, holidays, special hours) and the announcement.
// Data is embedded in each page by build.py as window.NAZA_EXCEPTIONS = {lang, items, announcement}.
// Renders:
//  - the detailed notice under the opening hours ([data-exceptions-notice] containers);
//  - a banner at the top of every page (#exceptions-banner) for exceptions that are
//    in progress or start within BANNER_DAYS_AHEAD days, followed by the announcement text;
//  - the announcement block on the home page ([data-announcement-block]): text + details.
// The announcement is shown from start_date to end_date (inclusive; no end_date = until removed).
// Items disappear automatically after their end date (Europe/Paris), without rebuilds.
(function (root) {
    "use strict";

    const BANNER_DAYS_AHEAD = 14;

    const MONTHS = {
        fr: ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"],
        uk: ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня",
            "вересня", "жовтня", "листопада", "грудня"],
    };
    // Plural weekday names, index = Date.getUTCDay() (0 = Sunday).
    const WEEKDAYS_PLURAL = {
        fr: ["dimanches", "lundis", "mardis", "mercredis", "jeudis", "vendredis", "samedis"],
        uk: ["неділі", "понеділки", "вівторки", "середи", "четверги", "п’ятниці", "суботи"],
    };
    const TEXT = {
        fr: { heading: "Informations exceptionnelles", closed: "atelier fermé", and: " et " },
        uk: { heading: "Тимчасові зміни графіка", closed: "ательє зачинене", and: " та " },
    };

    function parse(value) {
        const [year, month, day] = value.split("-").map(Number);
        return { year, month, day };
    }

    function weekday(d) {
        return new Date(Date.UTC(d.year, d.month - 1, d.day)).getUTCDay();
    }

    function dayNumber(lang, day) {
        return lang === "fr" && day === 1 ? "1er" : String(day);
    }

    function yearSuffix(lang, year) {
        return lang === "fr" ? ` ${year}` : ` ${year} року`;
    }

    function fullDate(lang, d, withYear) {
        const text = `${dayNumber(lang, d.day)} ${MONTHS[lang][d.month - 1]}`;
        return withYear ? text + yearSuffix(lang, d.year) : text;
    }

    function joinList(lang, values) {
        if (values.length === 1) return values[0];
        return values.slice(0, -1).join(", ") + TEXT[lang].and + values[values.length - 1];
    }

    // Lower-case date phrase for one item: "le 25 décembre 2026", "du 1er au 15 août 2026".
    function rangeText(lang, item) {
        const s = parse(item.start_date);
        const e = parse(item.end_date);
        if (item.start_date === item.end_date) {
            return (lang === "fr" ? "le " : "") + fullDate(lang, s, true);
        }
        let from;
        if (s.year === e.year && s.month === e.month) {
            from = dayNumber(lang, s.day);
        } else {
            from = fullDate(lang, s, s.year !== e.year);
        }
        const to = fullDate(lang, e, true);
        return lang === "fr" ? `du ${from} au ${to}` : `з ${from} до ${to}`;
    }

    // Lower-case date phrase for a group of items with identical type/label/hours.
    function groupDateText(lang, items) {
        const dates = items.map(item => parse(item.start_date));
        const singleDays = items.every(item => item.start_date === item.end_date);
        const sameMonth = dates.every(d => d.year === dates[0].year && d.month === dates[0].month);
        if (items.length > 1 && singleDays && sameMonth) {
            const days = joinList(lang, dates.map(d => dayNumber(lang, d.day)));
            const tail = ` ${MONTHS[lang][dates[0].month - 1]}` + yearSuffix(lang, dates[0].year);
            const wd = weekday(dates[0]);
            const sameWeekday = dates.every(d => weekday(d) === wd);
            if (sameWeekday) {
                return (lang === "fr" ? "les " : "") + `${WEEKDAYS_PLURAL[lang][wd]} ${days}${tail}`;
            }
            return (lang === "fr" ? "les " : "") + days + tail;
        }
        return items.map(item => rangeText(lang, item)).join("; ");
    }

    function capitalize(text) {
        return text ? text[0].toLocaleUpperCase() + text.slice(1) : text;
    }

    function formatHour(value) {
        return `${Number(value.slice(0, 2))}h${value.slice(3)}`;
    }

    // One line of text for a group of items.
    function lineText(lang, items) {
        const first = items[0];
        const dates = groupDateText(lang, items);
        if (first.type === "hours") {
            const open = formatHour(first.hours.open);
            const close = formatHour(first.hours.close);
            return lang === "fr"
                ? `${capitalize(dates)} : ouverture de ${open} à ${close}`
                : `${capitalize(dates)}: працюємо з ${open} до ${close}`;
        }
        const label = first.label && first.label[lang];
        const sep = lang === "fr" ? " : " : ": ";
        const prefix = label ? label + sep + dates : capitalize(dates);
        return `${prefix} — ${TEXT[lang].closed}`;
    }

    // Only single-day items of the same month are merged ("les jeudis 19 et 26 novembre");
    // every multi-day item gets its own line.
    function groupItems(items) {
        const groups = new Map();
        for (const item of items) {
            const key = item.start_date === item.end_date
                ? JSON.stringify([item.type, item.hours || null, item.label || null, item.start_date.slice(0, 7)])
                : `range:${item.id}`;
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(item);
        }
        return [...groups.values()];
    }

    function addDays(isoDate, days) {
        const d = parse(isoDate);
        return new Date(Date.UTC(d.year, d.month - 1, d.day + days)).toISOString().slice(0, 10);
    }

    // Lines for the notice (current + upcoming) and for the banner (current + soon).
    function computeLines(lang, items, today) {
        const upcoming = items.filter(item => item.end_date >= today)
            .sort((a, b) => a.start_date.localeCompare(b.start_date));
        const horizon = addDays(today, BANNER_DAYS_AHEAD);
        const soon = upcoming.filter(item => item.start_date <= horizon);
        return {
            notice: groupItems(upcoming).map(group => lineText(lang, group)),
            banner: groupItems(soon).map(group => lineText(lang, group)),
        };
    }

    // The announcement if it is shown today, else null.
    function activeAnnouncement(announcement, today) {
        if (!announcement || !announcement.text) return null;
        if (announcement.start_date > today) return null;
        if (announcement.end_date && announcement.end_date < today) return null;
        return announcement;
    }

    function todayInParis() {
        const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
            timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit",
        }).formatToParts(new Date()).map(part => [part.type, part.value]));
        return `${parts.year}-${parts.month}-${parts.day}`;
    }

    function render(doc, data) {
        const lang = data.lang === "uk" ? "uk" : "fr";
        const today = todayInParis();
        const lines = computeLines(lang, data.items || [], today);
        const announcement = activeAnnouncement(data.announcement, today);

        for (const container of doc.querySelectorAll("[data-exceptions-notice]")) {
            container.replaceChildren();
            container.hidden = !lines.notice.length;
            if (!lines.notice.length) continue;
            const heading = doc.createElement("h5");
            heading.className = "text-warning mb-2";
            heading.textContent = TEXT[lang].heading + (lang === "fr" ? "\u00a0:" : ":");
            container.appendChild(heading);
            for (const text of lines.notice) {
                const p = doc.createElement("p");
                p.className = "text-warning mb-1";
                p.textContent = text;
                container.appendChild(p);
            }
        }

        const banner = doc.getElementById("exceptions-banner");
        if (banner) {
            banner.replaceChildren();
            banner.hidden = !lines.banner.length && !announcement;
            for (const text of lines.banner) {
                const p = doc.createElement("p");
                p.textContent = text;
                banner.appendChild(p);
            }
            if (announcement) {
                const p = doc.createElement("p");
                p.className = "banner-announcement";
                p.textContent = announcement.text;
                banner.appendChild(p);
            }
        }

        for (const block of doc.querySelectorAll("[data-announcement-block]")) {
            block.replaceChildren();
            block.hidden = !announcement;
            if (!announcement) continue;
            const container = doc.createElement("div");
            container.className = "container";
            const box = doc.createElement("div");
            box.className = "announcement-box";
            const title = doc.createElement("p");
            title.className = "announcement-title";
            title.textContent = announcement.text;
            box.appendChild(title);
            const details = (announcement.details || "").split(/\n+/).map(line => line.trim()).filter(Boolean);
            for (const line of details) {
                const p = doc.createElement("p");
                p.className = "announcement-details";
                p.textContent = line;
                box.appendChild(p);
            }
            container.appendChild(box);
            block.appendChild(container);
        }
    }

    // The navbar is fixed to the top; keep it below the banner until the banner scrolls away.
    function placeNavbar(doc, win) {
        const nav = doc.getElementById("mainNav");
        const banner = doc.getElementById("exceptions-banner");
        if (!nav) return;
        const height = banner && !banner.hidden ? banner.offsetHeight : 0;
        nav.style.top = `${Math.max(0, height - win.scrollY)}px`;
    }

    function start(win) {
        const doc = win.document;
        const data = win.NAZA_EXCEPTIONS;
        if (!data) return;
        const update = () => {
            render(doc, data);
            placeNavbar(doc, win);
        };
        update();
        win.addEventListener("scroll", () => placeNavbar(doc, win), { passive: true });
        win.addEventListener("resize", () => placeNavbar(doc, win));
        win.setInterval(update, 60 * 1000);
    }

    const api = { computeLines, lineText, rangeText, groupDateText, activeAnnouncement, BANNER_DAYS_AHEAD };
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else {
        root.NazaExceptions = api;
        if (root.document) start(root);
    }
})(typeof window !== "undefined" ? window : this);
