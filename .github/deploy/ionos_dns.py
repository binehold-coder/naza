#!/usr/bin/env python3
"""Minimal IONOS DNS API client for naza-couture.fr (stdlib only).

API: https://api.hosting.ionos.com/dns/v1, header X-API-Key: "<prefix>.<secret>".
Key from env IONOS_API_KEY or from the file named in IONOS_API_KEY_FILE.

  show                     print every record of the zone (backup / audit)
  txt-add NAME VALUE       add a TXT record (ttl 60)
  txt-del NAME [VALUE]     delete TXT records with that name (and value)
  switch IP                @ and www -> A IP: edits existing A in place, removes
                           AAAA/CNAME on those two names only. Nothing else is touched.
"""
import json
import os
import sys
import urllib.error
import urllib.request

ZONE = "naza-couture.fr"
API = "https://api.hosting.ionos.com/dns/v1"
TTL_SWITCH = 300


def key() -> str:
    k = os.environ.get("IONOS_API_KEY", "").strip()
    if not k and os.environ.get("IONOS_API_KEY_FILE"):
        with open(os.environ["IONOS_API_KEY_FILE"], encoding="utf-8") as f:
            k = f.read().strip()
    if not k:
        sys.exit("IONOS_API_KEY is not set")
    return k


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "X-API-Key": key(), "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"IONOS API {method} {path}: HTTP {e.code} {e.read()[:300].decode(errors='replace')}")
    return json.loads(raw) if raw else None


def zone_id() -> str:
    for z in call("GET", "/zones"):
        if z.get("name") == ZONE:
            return z["id"]
    sys.exit(f"zone {ZONE} not found in this IONOS account")


def records(zid: str):
    return call("GET", f"/zones/{zid}").get("records", [])


def fqdn(name: str) -> str:
    name = name.rstrip(".")
    if name in ("", "@"):
        return ZONE
    return name if name.endswith(ZONE) else f"{name}.{ZONE}"


def unq(s: str) -> str:
    return s.strip().strip('"')


def fmt(r) -> str:
    return f"{r['type']:<6} {r['name']:<34} {r.get('content', '')}  ttl={r.get('ttl')}" + \
        ("  (disabled)" if r.get("disabled") else "")


def cmd_show(zid):
    for r in sorted(records(zid), key=lambda r: (r["name"], r["type"])):
        print(fmt(r))


def cmd_txt_add(zid, name, value):
    call("POST", f"/zones/{zid}/records",
         [{"name": fqdn(name), "type": "TXT", "content": value, "ttl": 60, "prio": 0, "disabled": False}])
    print(f"TXT added: {fqdn(name)}")


def cmd_txt_del(zid, name, value=None):
    n = 0
    for r in records(zid):
        if r["type"] == "TXT" and r["name"] == fqdn(name) and (value is None or unq(r["content"]) == value):
            call("DELETE", f"/zones/{zid}/records/{r['id']}")
            n += 1
    print(f"TXT deleted: {fqdn(name)} ({n})")


def cmd_switch(zid, ip):
    recs = records(zid)
    print("BEFORE (for rollback):")
    for r in recs:
        if r["name"] in (ZONE, f"www.{ZONE}") and r["type"] in ("A", "AAAA", "CNAME"):
            print("  " + fmt(r))
    for name in (ZONE, f"www.{ZONE}"):
        mine = [r for r in recs if r["name"] == name]
        a = [r for r in mine if r["type"] == "A"]
        # 1) put the new A in place first where an A already exists (no gap for that name)
        if a:
            call("PUT", f"/zones/{zid}/records/{a[0]['id']}",
                 {"content": ip, "ttl": TTL_SWITCH, "prio": 0, "disabled": False})
            for extra in a[1:]:
                call("DELETE", f"/zones/{zid}/records/{extra['id']}")
        # 2) remove what conflicts / points elsewhere
        for r in mine:
            if r["type"] in ("AAAA", "CNAME"):
                call("DELETE", f"/zones/{zid}/records/{r['id']}")
        # 3) CNAME-only names (www on Vercel): create the A right after deleting the CNAME
        if not a:
            call("POST", f"/zones/{zid}/records",
                 [{"name": name, "type": "A", "content": ip, "ttl": TTL_SWITCH, "prio": 0, "disabled": False}])
    print("AFTER:")
    for r in records(zid):
        if r["name"] in (ZONE, f"www.{ZONE}") and r["type"] in ("A", "AAAA", "CNAME"):
            print("  " + fmt(r))


def main(argv):
    if not argv:
        sys.exit(__doc__)
    zid = zone_id()
    c, args = argv[0], argv[1:]
    if c == "show" and not args:
        cmd_show(zid)
    elif c == "txt-add" and len(args) == 2:
        cmd_txt_add(zid, *args)
    elif c == "txt-del" and len(args) in (1, 2):
        cmd_txt_del(zid, *args)
    elif c == "switch" and len(args) == 1:
        cmd_switch(zid, args[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
