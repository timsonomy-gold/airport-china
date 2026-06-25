import json
import re
import time
import argparse
from collections import Counter, defaultdict
from io import StringIO
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

import generate_china_branch_airport_label_atlas as atlas


ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "china_scheduled_routes_wiki_2026-06.json"
CACHE_DIR = ROOT / "wiki_airport_pages"


def clean_text(value):
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\[\d+\]", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def alias_key(value):
    text = clean_text(value)
    text = re.sub(r"（.*?）|\(.*?\)", "", text)
    text = text.replace("/", "").replace("／", "")
    text = re.sub(r"(国际机场|机场|航空口岸)$", "", text)
    text = re.sub(r"(市|地区|自治州|盟)$", "", text)
    return re.sub(r"\s+", "", text)


def flatten_columns(table):
    cols = []
    for col in table.columns:
        if isinstance(col, tuple):
            parts = [clean_text(part) for part in col if not str(part).startswith("Unnamed")]
            cols.append("/".join(part for part in parts if part))
        else:
            cols.append(clean_text(col))
    table = table.copy()
    table.columns = cols
    return table


def make_aliases(airports):
    aliases = defaultdict(set)
    city_counter = Counter(alias_key(airport["city"].split()[0]) for airport in airports)
    for airport in airports:
        code = airport["iata"]
        values = {
            airport["name"],
            airport["short_name"],
            airport["name"].replace("国际机场", "").replace("机场", ""),
            airport["short_name"].replace("国际", ""),
            code,
        }
        city = airport["city"].split()[0]
        city_key = alias_key(city)
        if city_key and city_counter[city_key] == 1:
            values.add(city)
            values.add(city_key)
        for value in values:
            key = alias_key(value)
            if key:
                aliases[key].add(code)

    manual = {
        "北京首都": "PEK",
        "首都": "PEK",
        "北京大兴": "PKX",
        "大兴": "PKX",
        "上海虹桥": "SHA",
        "虹桥": "SHA",
        "上海浦东": "PVG",
        "浦东": "PVG",
        "成都天府": "TFU",
        "天府": "TFU",
        "成都双流": "CTU",
        "双流": "CTU",
        "广州白云": "CAN",
        "深圳宝安": "SZX",
        "重庆江北": "CKG",
        "西安咸阳": "XIY",
        "乌鲁木齐": "URC",
        "乌鲁木齐天山": "URC",
    }
    for key, code in manual.items():
        aliases[alias_key(key)].add(code)
    return {key: next(iter(codes)) for key, codes in aliases.items() if len(codes) == 1}


def fetch_page(title, cached_only=False):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{title}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    if cached_only:
        raise FileNotFoundError(f"no cached page for {title}")
    url = "https://zh.wikipedia.org/wiki/" + quote(title)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=8) as response:
        html = response.read().decode("utf-8", errors="replace")
    path.write_text(html, encoding="utf-8")
    time.sleep(0.08)
    return html


def table_value(row, candidates):
    for name in candidates:
        for col in row.index:
            if name in str(col):
                value = clean_text(row[col])
                if value and value.lower() != "nan":
                    return value
    return ""


def split_route_path(route_text):
    text = clean_text(route_text)
    text = re.sub(r"[（(].*?[）)]", "", text)
    parts = re.split(r"\s*(?:-|－|—|–|→|至|经)\s*", text)
    return [alias_key(part) for part in parts if alias_key(part)]


def find_code(value, aliases):
    key = alias_key(value)
    if key in aliases:
        return aliases[key]
    for alias, code in aliases.items():
        if alias and alias in key:
            return code
    return None


def add_route(routes, source, target, flight_no, schedule, page_title):
    if not source or not target or source == target:
        return
    item = routes[(source, target)]
    item["from"] = source
    item["to"] = target
    if flight_no:
        item["flightNos"].add(flight_no)
    if schedule:
        item["conditions"].add(schedule)
    item["sources"].add(f"维基:{page_title}")
    item["scheduleKnown"] = True


def parse_airport_page(airport, aliases, cached_only=False):
    routes = defaultdict(lambda: {"flightNos": set(), "conditions": set(), "sources": set(), "scheduleKnown": False})
    try:
        html = fetch_page(airport["name"], cached_only=cached_only)
        tables = pd.read_html(StringIO(html))
    except Exception as exc:
        return routes, f"{airport['iata']} {airport['name']}: {exc}"

    source_code = airport["iata"]
    source_aliases = {
        alias_key(airport["city"].split()[0]),
        alias_key(airport["short_name"]),
        alias_key(airport["name"].replace("机场", "").replace("国际机场", "")),
    }
    for table in tables:
        table = flatten_columns(table)
        columns = "".join(str(col) for col in table.columns)
        if not any(token in columns for token in ("航程", "航班", "班期", "目的地", "航点")):
            continue
        if "吞吐" in columns or "跑道" in columns:
            continue
        for _, row in table.iterrows():
            schedule = table_value(row, ["班期", "每周", "备注"])
            flight_no = table_value(row, ["航班号", "航班", "通航地"])
            route_text = table_value(row, ["航程"])
            destination = table_value(row, ["目的地", "航点", "机场"])
            path_keys = split_route_path(route_text)
            path_codes = [aliases.get(key) for key in path_keys]
            path_codes = [code for code in path_codes if code]
            if source_code in path_codes:
                idxs = [idx for idx, code in enumerate(path_codes) if code == source_code]
                for idx in idxs:
                    for neighbor_idx in (idx - 1, idx + 1):
                        if 0 <= neighbor_idx < len(path_codes):
                            neighbor = path_codes[neighbor_idx]
                            add_route(routes, source_code, neighbor, flight_no, schedule, airport["name"])
                            add_route(routes, neighbor, source_code, flight_no, schedule, airport["name"])
                continue

            if path_keys and any(key in source_aliases for key in path_keys):
                for code in path_codes:
                    add_route(routes, source_code, code, flight_no, schedule, airport["name"])
                    add_route(routes, code, source_code, flight_no, schedule, airport["name"])
                continue

            dest_code = find_code(destination, aliases)
            if dest_code:
                add_route(routes, source_code, dest_code, flight_no, schedule, airport["name"])
                add_route(routes, dest_code, source_code, flight_no, schedule, airport["name"])
    return routes, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached-only", action="store_true", help="only parse pages already saved in wiki_airport_pages")
    args = parser.parse_args()
    airports = atlas.load_airports()
    aliases = make_aliases(airports)
    all_routes = defaultdict(lambda: {"flightNos": set(), "conditions": set(), "sources": set(), "scheduleKnown": False})
    errors = []
    for airport in airports:
        routes, error = parse_airport_page(airport, aliases, cached_only=args.cached_only)
        if error:
            errors.append(error)
        for key, item in routes.items():
            target = all_routes[key]
            target["from"] = item["from"]
            target["to"] = item["to"]
            target["flightNos"].update(item["flightNos"])
            target["conditions"].update(item["conditions"])
            target["sources"].update(item["sources"])
            target["scheduleKnown"] = target["scheduleKnown"] or item["scheduleKnown"]

    payload = []
    for item in all_routes.values():
        payload.append(
            {
                "from": item["from"],
                "to": item["to"],
                "flightNos": sorted(item["flightNos"])[:10],
                "conditions": sorted(item["conditions"])[:8],
                "sources": sorted(item["sources"])[:6],
                "scheduleKnown": item["scheduleKnown"],
            }
        )
    payload.sort(key=lambda route: (route["from"], route["to"]))
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    covered = {route["from"] for route in payload} | {route["to"] for route in payload}
    print(f"wrote {OUT_JSON}")
    print(f"scheduled directed routes: {len(payload)}")
    print(f"covered airports: {len(covered)} / {len(airports)}")
    print(f"page errors: {len(errors)}")
    if errors:
        print("\\n".join(errors[:20]))


if __name__ == "__main__":
    main()
