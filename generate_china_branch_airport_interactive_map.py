import csv
import json
from pathlib import Path

import generate_china_branch_airport_label_atlas as atlas
import generate_china_airport_level_map as base


ROOT = Path(__file__).resolve().parent
OUT_HTML = ROOT / "china_branch_airports_interactive_2026-06.html"
OPENFLIGHTS_ROUTES = ROOT / "openflights_routes.dat"
SCHEDULED_ROUTES = ROOT / "china_scheduled_routes_wiki_2026-06.json"
FLIGHTCONNECTIONS_ROUTES = ROOT / "china_current_routes_flightconnections_2026-06.json"

WIDTH = 5200
HEIGHT = 3600
MARGIN = (210, 230, 210, 220)

SUPPLEMENTAL_ROUTE_LINKS = {
    "URC": [
        "AAT", "ACF", "BPL", "DHH", "FYN", "HJB", "HMI", "HTN", "IQM",
        "JBK", "KCA", "KHG", "KJI", "KRL", "KRY", "LTJ", "NLT", "RQA",
        "SHF", "TCG", "TLQ", "TWC", "YIN", "YTW", "ZFL",
    ],
    "HRB": [
        "DQA", "DTU", "FYJ", "HEK", "JGD", "JMU", "JSJ", "JXA", "LDS",
        "MDG", "NDG", "OHE",
    ],
    "KMG": [
        "BSD", "CWJ", "DIG", "DLU", "JHG", "JMJ", "LJG", "LNJ", "LUM",
        "NLH", "SYM", "TCZ", "WNH", "ZAT",
    ],
    "LHW": ["DNH", "GXH", "IQN", "JGN", "JIC", "LNL", "THQ", "XNN", "YZY", "ZHY"],
    "XIY": ["AKA", "ENY", "GYU", "HZG", "IQN", "UYN", "YCU", "ZHY"],
    "HET": [
        "AXF", "BAV", "CIF", "EJN", "ERL", "HLD", "HLH", "HUO", "NZH",
        "NZL", "RHT", "RLK", "TGO", "UCB", "WUA", "XIL", "YIE",
    ],
    "SHE": ["AOG", "CHG", "DDG", "DLC", "JNZ", "YKH"],
    "CGQ": ["DBC", "NBS", "TNH", "YNJ", "YSQ"],
    "LXA": ["APJ", "BPX", "DDR", "LGZ", "LZY", "NGQ", "RKZ"],
    "KWE": ["ACX", "AVA", "BFJ", "HZH", "KJH", "LLB", "LPF", "TEN"],
    "CKG": ["JIQ", "LIA", "WXN", "WSK", "YBP"],
}


def build_route_payload(airport_codes):
    route_map = {}

    def ensure_route(
        source,
        target,
        source_name,
        airline=None,
        equipment=None,
        flight_no=None,
        conditions=None,
        evidence="legacy",
    ):
        if source not in airport_codes or target not in airport_codes or source == target:
            return
        item = route_map.setdefault(
            (source, target),
            {
                "from": source,
                "to": target,
                "sources": set(),
                "airlines": set(),
                "equipment": set(),
                "flightNos": set(),
                "conditions": set(),
                "evidence": set(),
            },
        )
        item["sources"].add(source_name)
        item["evidence"].add(evidence)
        if airline and airline != r"\N":
            item["airlines"].add(airline)
        if equipment and equipment != r"\N":
            item["equipment"].update(part for part in equipment.split() if part)
        if flight_no:
            item["flightNos"].add(flight_no)
        for condition in conditions or []:
            if condition:
                item["conditions"].add(condition)

    if SCHEDULED_ROUTES.exists():
        scheduled_routes = json.loads(SCHEDULED_ROUTES.read_text(encoding="utf-8"))
        for route in scheduled_routes:
            evidence = "conditioned" if route.get("conditions") or route.get("flightNos") else "published"
            source_name = "维基班期/航点表"
            ensure_route(
                route.get("from"),
                route.get("to"),
                source_name,
                flight_no="、".join(route.get("flightNos") or []),
                conditions=route.get("conditions") or [],
                evidence=evidence,
            )

    if FLIGHTCONNECTIONS_ROUTES.exists():
        payload = json.loads(FLIGHTCONNECTIONS_ROUTES.read_text(encoding="utf-8"))
        for route in payload.get("routes", []):
            ensure_route(
                route.get("from"),
                route.get("to"),
                "FlightConnections 当前直飞",
                conditions=route.get("conditions") or [],
                evidence="current",
            )

    if OPENFLIGHTS_ROUTES.exists():
        with OPENFLIGHTS_ROUTES.open(encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) < 9:
                    continue
                ensure_route(row[2], row[4], "OpenFlights 历史公开表", row[0], row[8], evidence="legacy")

    # The public OpenFlights table is old and misses many newer Chinese branch airports.
    # Keep a small hand-curated supplement for recently opened or under-covered regional links.
    for source, targets in SUPPLEMENTAL_ROUTE_LINKS.items():
        for target in targets:
            ensure_route(source, target, "人工补充", None, None, evidence="legacy")
            ensure_route(target, source, "人工补充", None, None, evidence="legacy")

    routes = []
    for item in route_map.values():
        evidence = item["evidence"]
        source_level = (
            "current"
            if "current" in evidence
            else "conditioned"
            if "conditioned" in evidence
            else "published"
            if "published" in evidence
            else "legacy"
        )
        routes.append(
            {
                "from": item["from"],
                "to": item["to"],
                "sources": sorted(item["sources"]),
                "airlines": sorted(item["airlines"])[:8],
                "airlineCount": len(item["airlines"]),
                "equipment": sorted(item["equipment"])[:6],
                "flightNos": sorted(item["flightNos"])[:8],
                "conditions": sorted(item["conditions"])[:8],
                "sourceLevel": source_level,
                "conditionKnown": bool(item["conditions"]),
            }
        )
    return sorted(routes, key=lambda route: (route["from"], route["to"]))


def projected_bounds(airports):
    rings = []
    xs, ys = [], []
    features = json.loads(base.PROVINCES_GEOJSON.read_text(encoding="utf-8"))["features"]
    for feature in features:
        for ring in base.iter_polygon_rings(feature["geometry"]):
            projected = [base.albers_project(lon, lat) for lon, lat in ring]
            if len(projected) >= 3:
                rings.append(projected)
                xs.extend([p[0] for p in projected])
                ys.extend([p[1] for p in projected])
    for airport in airports:
        x, y = base.albers_project(airport["lon"], airport["lat"])
        airport["raw_x"] = x
        airport["raw_y"] = y
        xs.append(x)
        ys.append(y)
    return rings, min(xs), max(xs), min(ys), max(ys)


def make_mapper(min_x, max_x, min_y, max_y):
    left, top, right, bottom = MARGIN
    scale = min((WIDTH - left - right) / (max_x - min_x), (HEIGHT - top - bottom) / (max_y - min_y))

    def to_canvas(point):
        x, y = point
        return left + (x - min_x) * scale, top + (max_y - y) * scale

    return to_canvas


def path_from_ring(points, mapper):
    coords = [mapper(point) for point in points]
    if not coords:
        return ""
    d = [f"M {coords[0][0]:.1f} {coords[0][1]:.1f}"]
    d.extend(f"L {x:.1f} {y:.1f}" for x, y in coords[1:])
    d.append("Z")
    return " ".join(d)


def html_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main():
    airports = atlas.load_airports()
    rings, min_x, max_x, min_y, max_y = projected_bounds(airports)
    mapper = make_mapper(min_x, max_x, min_y, max_y)

    paths = "\n".join(
        f'<path class="province" d="{path_from_ring(ring, mapper)}"></path>' for ring in rings
    )
    airport_payload = []
    for airport in airports:
        x, y = mapper((airport["raw_x"], airport["raw_y"]))
        airport_payload.append(
            {
                "name": airport["name"],
                "shortName": airport["short_name"],
                "iata": airport["iata"],
                "icao": airport["icao"],
                "cls": airport["flight_area_class"],
                "city": airport["city"],
                "type": airport["type"],
                "opened": airport["opened"],
                "lon": round(airport["lon"], 6),
                "lat": round(airport["lat"], 6),
                "x": round(x, 2),
                "y": round(y, 2),
                "branch": airport["is_branch"],
            }
        )

    route_payload = build_route_payload({airport["iata"] for airport in airport_payload})

    region_payload = [
        {
            "name": region["name"],
            "extent": list(region["extent"]),
        }
        for region in atlas.REGIONS
    ]

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>中国支线机场可缩放查询图</title>
  <style>
    :root {{
      --bg: #f6f9fb;
      --ink: #1d2d3d;
      --muted: #657487;
      --line: #c8d5df;
      --panel: rgba(255, 255, 255, 0.94);
      --shadow: 0 12px 32px rgba(31, 49, 67, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    html {{ height: 100%; }}
    body {{
      margin: 0;
      width: 100%;
      height: 100%;
      min-height: 100vh;
      min-height: 100dvh;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "STHeiti", "Microsoft YaHei", sans-serif;
      overflow: hidden;
    }}
    .app {{
      position: fixed;
      inset: 0;
      display: grid;
      grid-template-columns: 1fr 360px;
      grid-template-rows: minmax(0, 1fr);
      height: 100vh;
      height: 100dvh;
      width: 100vw;
      min-height: 620px;
      overflow: hidden;
    }}
    .map-wrap {{
      position: relative;
      min-width: 0;
      min-height: 0;
      height: 100%;
      background: #eef4f8;
      overflow: hidden;
      contain: layout paint size;
    }}
    svg {{
      display: block;
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      min-width: 100%;
      min-height: 100%;
      max-width: 100%;
      max-height: 100%;
      cursor: grab;
      user-select: none;
      touch-action: none;
    }}
    svg.dragging {{ cursor: grabbing; }}
    .province {{
      fill: #dfeaf0;
      stroke: #b7c8d5;
      stroke-width: 2;
      vector-effect: non-scaling-stroke;
    }}
    .airport-hit {{
      cursor: pointer;
      stroke: #fff;
      stroke-width: 5;
      filter: drop-shadow(0 1px 1px rgba(20, 34, 48, 0.22));
    }}
    .major-hit {{
      fill: #9faab4;
      opacity: 0.62;
    }}
    .route-line {{
      fill: none;
      stroke-width: 2.1;
      stroke-linecap: round;
      opacity: 0.46;
      pointer-events: none;
      vector-effect: non-scaling-stroke;
      mix-blend-mode: multiply;
    }}
    .route-line.outgoing {{ stroke: #176fb3; }}
    .route-line.incoming {{ stroke: #d47a1f; }}
    .route-line.published {{ opacity: 0.38; }}
    .route-line.legacy {{
      opacity: 0.24;
      stroke-dasharray: 8 8;
    }}
    .route-endpoint {{
      pointer-events: none;
      stroke: #fff;
      stroke-width: 3;
      filter: drop-shadow(0 1px 2px rgba(20, 34, 48, 0.24));
    }}
    .route-endpoint.outgoing {{ fill: #176fb3; }}
    .route-endpoint.incoming {{ fill: #d47a1f; }}
    .route-endpoint.both {{ fill: #7b5bb2; }}
    .route-label {{
      pointer-events: none;
      font-size: 48px;
      font-weight: 800;
      fill: #17425d;
      paint-order: stroke;
      stroke: rgba(255,255,255,0.96);
      stroke-width: 12px;
      stroke-linejoin: round;
    }}
    .route-key {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin: 2px 10px 2px 0;
      white-space: nowrap;
    }}
    .route-swatch {{
      width: 18px;
      height: 3px;
      border-radius: 999px;
      display: inline-block;
    }}
    .route-note {{
      color: #657487;
      font-size: 12px;
      line-height: 1.55;
      margin-top: 4px;
    }}
    .airport-hit.dimmed {{
      opacity: 0.16;
    }}
    .airport-hit.connected-hit {{
      stroke: #145f92;
      stroke-width: 7;
    }}
    .airport-hit.selected-hit {{
      stroke: #122f44;
      stroke-width: 9;
    }}
    .label {{
      pointer-events: none;
      font-size: 86px;
      font-weight: 700;
      fill: #203447;
      paint-order: stroke;
      stroke: rgba(255,255,255,0.94);
      stroke-width: 18px;
      stroke-linejoin: round;
    }}
    .label.hidden {{ display: none; }}
    .label.major-label {{ fill: #6b7885; font-size: 66px; font-weight: 600; }}
    .hud {{
      position: absolute;
      left: 24px;
      top: 22px;
      display: flex;
      gap: 12px;
      align-items: flex-start;
      flex-wrap: wrap;
      max-width: calc(100% - 48px);
      pointer-events: none;
    }}
    .controls {{
      position: absolute;
      left: 24px;
      bottom: 18px;
      z-index: 5;
      pointer-events: auto;
    }}
    .title {{
      padding: 14px 18px 13px;
      background: var(--panel);
      border: 1px solid #d7e1e8;
      border-radius: 8px;
      box-shadow: var(--shadow);
      pointer-events: auto;
    }}
    h1 {{
      margin: 0;
      font-size: 25px;
      letter-spacing: 0;
      line-height: 1.15;
    }}
    .subtitle {{
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    .zoom-box {{
      width: 300px;
      padding: 10px 11px 9px;
      background: var(--panel);
      border: 1px solid #d7e1e8;
      border-radius: 8px;
      box-shadow: var(--shadow);
      pointer-events: auto;
    }}
    .zoom-row {{
      display: grid;
      grid-template-columns: 38px 28px 1fr 28px 43px;
      align-items: center;
      gap: 6px;
      margin-top: 6px;
    }}
    .zoom-row:first-child {{ margin-top: 0; }}
    .control-label {{
      color: #506477;
      font-size: 12px;
      white-space: nowrap;
    }}
    .toggle-row {{
      margin-top: 7px;
      display: flex;
      align-items: center;
      gap: 6px;
      color: #405469;
      font-size: 12px;
      line-height: 1.25;
    }}
    .toggle-row input {{
      width: 14px;
      height: 14px;
      margin: 0;
    }}
    button, input, select {{
      font: inherit;
    }}
    button {{
      border: 1px solid #cad7e0;
      background: #fff;
      color: #243749;
      border-radius: 6px;
      height: 28px;
      cursor: pointer;
    }}
    button:hover {{ border-color: #91a8ba; background: #f8fbfd; }}
    .fit-button {{
      width: 100%;
      margin-top: 7px;
      font-size: 12px;
    }}
    input[type="range"] {{ width: 100%; }}
    .scale-readout {{
      font-size: 12px;
      color: #405469;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}
    .side {{
      border-left: 1px solid #d8e3eb;
      background: #fff;
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }}
    .side header {{
      padding: 22px 20px 16px;
      border-bottom: 1px solid #e1e9ef;
    }}
    .search {{
      width: 100%;
      height: 40px;
      border: 1px solid #cbd8e2;
      border-radius: 8px;
      padding: 0 12px;
      font-size: 15px;
      outline: none;
    }}
    .search:focus {{ border-color: #357fb5; box-shadow: 0 0 0 3px rgba(53,127,181,.16); }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 12px;
    }}
    .chip {{
      height: 30px;
      padding: 0 10px;
      font-size: 13px;
    }}
    .chip.active {{
      border-color: #357fb5;
      color: #145f92;
      background: #eaf5fc;
    }}
    .regions {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 7px;
      padding: 14px 20px;
      border-bottom: 1px solid #e1e9ef;
    }}
    .region-btn {{
      height: 36px;
      font-size: 13px;
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .result-meta {{
      padding: 12px 20px 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .list {{
      overflow: auto;
      padding: 0 12px 16px;
    }}
    .item {{
      width: 100%;
      min-height: 58px;
      height: auto;
      border: 0;
      border-radius: 8px;
      background: #fff;
      display: grid;
      grid-template-columns: 48px 1fr;
      gap: 10px;
      padding: 9px 8px;
      text-align: left;
    }}
    .item:hover, .item.selected {{ background: #eef6fb; }}
    .code {{
      display: inline-grid;
      place-items: center;
      height: 34px;
      min-width: 44px;
      border-radius: 7px;
      color: #fff;
      font-weight: 800;
      font-size: 13px;
      letter-spacing: 0;
      align-self: start;
    }}
    .name {{
      font-size: 15px;
      font-weight: 700;
      line-height: 1.25;
      color: #233648;
    }}
    .meta {{
      margin-top: 4px;
      font-size: 12px;
      color: #667789;
      line-height: 1.35;
    }}
    .detail {{
      margin: 0 20px 18px;
      padding: 14px;
      border: 1px solid #dbe5ec;
      border-radius: 8px;
      background: #f8fbfd;
      color: #405469;
      font-size: 13px;
      line-height: 1.65;
    }}
    .detail strong {{
      color: #203447;
      font-size: 16px;
    }}
    .legend {{
      position: absolute;
      left: 24px;
      top: 116px;
      background: var(--panel);
      border: 1px solid #d7e1e8;
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 9px 11px;
      display: flex;
      gap: 12px;
      align-items: center;
      color: #506477;
      font-size: 12px;
      pointer-events: none;
    }}
    .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    @media (max-width: 980px) {{
      body {{ overflow: auto; }}
      .app {{
        grid-template-columns: 1fr;
        grid-template-rows: minmax(520px, 68vh) auto;
        grid-template-rows: minmax(520px, 68dvh) auto;
      }}
      .map-wrap {{ height: auto; min-height: 520px; }}
      .side {{ border-left: 0; border-top: 1px solid #d8e3eb; max-height: none; }}
      .hud {{ left: 12px; top: 12px; }}
      .controls {{ left: 12px; bottom: 12px; }}
      .title h1 {{ font-size: 19px; }}
      .subtitle {{ white-space: normal; }}
      .zoom-box {{ width: 300px; max-width: calc(100vw - 24px); }}
      .legend {{ left: 12px; top: 102px; flex-wrap: wrap; max-width: calc(100% - 24px); }}
    }}
  </style>
</head>
<body>
  <main class="app" id="app">
    <section class="map-wrap">
      <svg id="map" viewBox="0 0 {WIDTH} {HEIGHT}" aria-label="中国大陆支线机场可缩放地图">
        <g id="mapLayer">{paths}</g>
        <g id="routeLayer"></g>
        <g id="airportLayer"></g>
        <g id="labelLayer"></g>
      </svg>
      <div class="hud">
        <div class="title">
          <h1>中国大陆支线机场查询图</h1>
          <div class="subtitle">截至 2026-06-24，默认显示大陆全部在运营民用运输机场 269 座</div>
        </div>
      </div>
      <div class="controls">
        <div class="zoom-box">
          <div class="zoom-row">
            <div class="control-label">比例</div>
            <button id="zoomOut" title="缩小">−</button>
            <input id="zoomSlider" type="range" min="0.75" max="8" step="0.05" value="1">
            <button id="zoomIn" title="放大">＋</button>
            <div id="scaleReadout" class="scale-readout">1.00×</div>
          </div>
          <div class="zoom-row">
            <div class="control-label">文字</div>
            <button id="labelDown" title="缩小文字">−</button>
            <input id="labelSlider" type="range" min="0.45" max="2.2" step="0.05" value="1.25">
            <button id="labelUp" title="放大文字">＋</button>
            <div id="labelReadout" class="scale-readout">1.25×</div>
          </div>
          <label class="toggle-row">
            <input id="hideLabels" type="checkbox">
            隐藏全部名称，仅点击点位时显示该机场
          </label>
          <button id="fitMap" class="fit-button" title="回到全国总览">适应全图</button>
        </div>
      </div>
      <div class="legend">
        <span><i class="dot" style="background:#da9f2f"></i>4D</span>
        <span><i class="dot" style="background:#2377b8"></i>4C</span>
        <span><i class="dot" style="background:#589769"></i>3C</span>
        <span><i class="dot" style="background:#78828f"></i>1B</span>
        <span><i class="dot" style="background:#9faab4"></i>4E/4F 干线/枢纽</span>
      </div>
    </section>
    <aside class="side">
      <header>
        <input id="search" class="search" placeholder="搜索机场名、城市、IATA 或 ICAO" autocomplete="off">
        <div class="filters">
          <button class="chip active" data-class="all" aria-pressed="true">全部民用运输 269</button>
          <button class="chip" data-class="branch" aria-pressed="false">支线/中小型 214</button>
          <button class="chip" data-class="major" aria-pressed="false">干线/枢纽 55</button>
          <button class="chip" data-class="4D" aria-pressed="false">4D 36</button>
          <button class="chip" data-class="4C" aria-pressed="false">4C 174</button>
          <button class="chip" data-class="3C" aria-pressed="false">3C 3</button>
          <button class="chip" data-class="1B" aria-pressed="false">1B 1</button>
        </div>
      </header>
      <div class="regions" id="regions"></div>
      <div class="result-meta" id="resultMeta"></div>
      <div class="list" id="list"></div>
      <div class="detail" id="detail">选择机场后显示坐标、等级和城市信息。</div>
    </aside>
  </main>
  <script>
    const AIRPORTS = {json.dumps(airport_payload, ensure_ascii=False)};
    const REGIONS = {json.dumps(region_payload, ensure_ascii=False)};
    const ROUTES = {json.dumps(route_payload, ensure_ascii=False)};
    const SVG_W = {WIDTH};
    const SVG_H = {HEIGHT};
    const BASE_PAD = 150;
    const classColor = {{
      "4F": "#b7222d",
      "4E": "#e67621",
      "4D": "#da9f2f",
      "4C": "#2377b8",
      "3C": "#589769",
      "1B": "#78828f"
    }};
    const classRadius = {{
      "4F": 16,
      "4E": 15,
      "4D": 22,
      "4C": 19,
      "3C": 17,
      "1B": 17
    }};

    const app = document.getElementById("app");
    const svg = document.getElementById("map");
    const mapLayer = document.getElementById("mapLayer");
    const routeLayer = document.getElementById("routeLayer");
    const airportLayer = document.getElementById("airportLayer");
    const labelLayer = document.getElementById("labelLayer");
    const slider = document.getElementById("zoomSlider");
    const labelSlider = document.getElementById("labelSlider");
    const hideLabels = document.getElementById("hideLabels");
    const scaleReadout = document.getElementById("scaleReadout");
    const labelReadout = document.getElementById("labelReadout");
    const search = document.getElementById("search");
    const list = document.getElementById("list");
    const resultMeta = document.getElementById("resultMeta");
    const detail = document.getElementById("detail");
    const regionBox = document.getElementById("regions");
    const chips = [...document.querySelectorAll(".chip")];
    const airportsByIata = new Map(AIRPORTS.map(airport => [airport.iata, airport]));
    const outgoingRoutesByIata = new Map(AIRPORTS.map(airport => [airport.iata, []]));
    const incomingRoutesByIata = new Map(AIRPORTS.map(airport => [airport.iata, []]));
    for (const route of ROUTES) {{
      outgoingRoutesByIata.get(route.from)?.push(route);
      incomingRoutesByIata.get(route.to)?.push(route);
    }}

    let transform = {{ k: 1, x: 0, y: 0 }};
    let fitTransform = {{ k: 1, x: 0, y: 0 }};
    let labelScale = Number(labelSlider.value);
    let activeClasses = new Set(["all"]);
    let selected = null;
    let dragging = false;
    let dragMoved = false;
    let lastPoint = null;
    let pointerDownPoint = null;

    function svgPoint(event) {{
      const pt = svg.createSVGPoint();
      pt.x = event.clientX;
      pt.y = event.clientY;
      const ctm = svg.getScreenCTM().inverse();
      const p = pt.matrixTransform(ctm);
      return {{ x: p.x, y: p.y }};
    }}

    function setTransform(next) {{
      transform = {{
        k: Math.max(0.75, Math.min(8, next.k)),
        x: next.x,
        y: next.y
      }};
      mapLayer.setAttribute("transform", `translate(${{transform.x}} ${{transform.y}}) scale(${{transform.k}})`);
      slider.value = transform.k.toFixed(2);
      scaleReadout.textContent = `${{transform.k.toFixed(2)}}×`;
      drawAirports();
    }}

    function syncViewportSize() {{
      const width = Math.max(window.innerWidth || document.documentElement.clientWidth || 0, 640);
      const height = Math.max(window.innerHeight || document.documentElement.clientHeight || 0, 620);
      app.style.width = `${{width}}px`;
      app.style.height = `${{height}}px`;
      requestAnimationFrame(drawAirports);
    }}

    function contentBounds() {{
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const airport of AIRPORTS) {{
        minX = Math.min(minX, airport.x);
        minY = Math.min(minY, airport.y);
        maxX = Math.max(maxX, airport.x);
        maxY = Math.max(maxY, airport.y);
      }}
      return {{
        minX: minX - BASE_PAD,
        minY: minY - BASE_PAD,
        maxX: maxX + BASE_PAD,
        maxY: maxY + BASE_PAD
      }};
    }}

    function fitMap(resetSelection = false) {{
      if (resetSelection) selected = null;
      const b = contentBounds();
      const k = Math.min(SVG_W / (b.maxX - b.minX), SVG_H / (b.maxY - b.minY));
      fitTransform = {{
        k,
        x: (SVG_W - (b.minX + b.maxX) * k) / 2,
        y: (SVG_H - (b.minY + b.maxY) * k) / 2
      }};
      setTransform(fitTransform);
    }}

    function zoomAt(point, nextK) {{
      const oldK = transform.k;
      const k = Math.max(0.75, Math.min(8, nextK));
      const worldX = (point.x - transform.x) / oldK;
      const worldY = (point.y - transform.y) / oldK;
      setTransform({{
        k,
        x: point.x - worldX * k,
        y: point.y - worldY * k
      }});
    }}

    function airportScreen(a) {{
      return {{
        x: transform.x + a.x * transform.k,
        y: transform.y + a.y * transform.k
      }};
    }}

    function airportMatchesFilter(a, filter) {{
      if (filter === "branch") return a.branch;
      if (filter === "major") return !a.branch;
      return a.cls === filter;
    }}

    function airportVisibleByClass(a) {{
      if (activeClasses.has("all")) return true;
      return [...activeClasses].some(filter => airportMatchesFilter(a, filter));
    }}

    function airportVisibleBySearch(a) {{
      const q = search.value.trim().toLowerCase();
      if (!q) return true;
      return [a.name, a.shortName, a.iata, a.icao, a.city, a.cls].some(v => String(v).toLowerCase().includes(q));
    }}

    function visibleAirports() {{
      return AIRPORTS.filter(a => airportVisibleByClass(a) && airportVisibleBySearch(a));
    }}

    function routeGroups(a) {{
      return {{
        outgoing: outgoingRoutesByIata.get(a.iata) || [],
        incoming: incomingRoutesByIata.get(a.iata) || []
      }};
    }}

    function routeAirportCodes(groups) {{
      const codes = new Set();
      for (const route of groups.outgoing) codes.add(route.to);
      for (const route of groups.incoming) codes.add(route.from);
      return codes;
    }}

    function labelAllowed(a) {{
      if (selected && selected.iata === a.iata) return true;
      if (!a.branch) return transform.k >= 3.8;
      if (transform.k >= 2.1) return true;
      if (transform.k >= 1.35) return a.cls === "4D" || a.cls === "3C" || a.cls === "1B";
      return a.cls === "4D";
    }}

    function drawAirports() {{
      routeLayer.replaceChildren();
      airportLayer.replaceChildren();
      labelLayer.replaceChildren();
      const visible = visibleAirports();
      const groups = selected ? routeGroups(selected) : {{ outgoing: [], incoming: [] }};
      const routeCodes = routeAirportCodes(groups);
      drawRoutes(groups);
      const searchActive = search.value.trim().length > 0;
      const sorted = [...visible].sort((a, b) => Number(a.branch) - Number(b.branch));

      for (const a of sorted) {{
        const p = airportScreen(a);
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        const classes = [a.branch ? "airport-hit" : "airport-hit major-hit"];
        if (selected && selected.iata === a.iata) classes.push("selected-hit");
        if (routeCodes.has(a.iata)) classes.push("connected-hit");
        if (selected && routeCodes.size && selected.iata !== a.iata && !routeCodes.has(a.iata)) classes.push("dimmed");
        circle.setAttribute("cx", p.x);
        circle.setAttribute("cy", p.y);
        circle.setAttribute("r", classRadius[a.cls] || 5);
        circle.setAttribute("class", classes.join(" "));
        circle.setAttribute("fill", a.branch ? classColor[a.cls] : "#9faab4");
        circle.style.opacity = "1";
        airportLayer.appendChild(circle);
      }}

      const labelCandidates = visible.filter(a => {{
        if (hideLabels.checked) return selected && selected.iata === a.iata;
        if (searchActive) return true;
        if (!activeClasses.has("all")) return true;
        return labelAllowed(a);
      }});
      for (const a of labelCandidates) {{
        const p = airportScreen(a);
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", p.x + 10);
        text.setAttribute("y", p.y - 24 * labelScale);
        text.setAttribute("class", a.branch ? "label" : "label major-label");
        text.style.fontSize = `${{a.branch ? 86 * labelScale : 66 * labelScale}}px`;
        text.style.strokeWidth = `${{a.branch ? 18 * labelScale : 14 * labelScale}}px`;
        text.textContent = `${{a.iata}} ${{a.shortName}}`;
        labelLayer.appendChild(text);
      }}

      renderList(visible);
    }}

    function routeCurvePath(start, end, direction) {{
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const distance = Math.hypot(dx, dy) || 1;
      const mx = (start.x + end.x) / 2;
      const my = (start.y + end.y) / 2;
      const bend = Math.min(280, Math.max(55, distance * 0.12)) * direction;
      const cx = mx - (dy / distance) * bend;
      const cy = my + (dx / distance) * bend;
      return `M ${{start.x.toFixed(1)}} ${{start.y.toFixed(1)}} Q ${{cx.toFixed(1)}} ${{cy.toFixed(1)}} ${{end.x.toFixed(1)}} ${{end.y.toFixed(1)}}`;
    }}

    function appendRoutePath(path, className) {{
      const item = document.createElementNS("http://www.w3.org/2000/svg", "path");
      item.setAttribute("class", className);
      item.setAttribute("d", path);
      routeLayer.appendChild(item);
    }}

    function routeLabelTarget(route, direction) {{
      return direction === "outgoing" ? airportsByIata.get(route.to) : airportsByIata.get(route.from);
    }}

    function drawRoutes(groups) {{
      const total = groups.outgoing.length + groups.incoming.length;
      if (!selected || !total) return;
      const start = airportScreen(selected);
      const showRouteLabels = total <= 30 || transform.k >= 2.4;
      const endpoints = new Map();
      const labeledEndpoints = new Set();
      const routeJobs = [
        ...groups.outgoing.map(route => ({{ route, direction: "outgoing", sign: 1 }})),
        ...groups.incoming.map(route => ({{ route, direction: "incoming", sign: -1 }}))
      ];

      for (const job of routeJobs) {{
        const target = routeLabelTarget(job.route, job.direction);
        if (!target) continue;
        const end = airportScreen(target);
        const path = routeCurvePath(start, end, job.sign);
        appendRoutePath(path, `route-line ${{job.direction}} ${{job.route.sourceLevel || "legacy"}}`);
        const endpoint = endpoints.get(target.iata) || {{ airport: target, outgoing: false, incoming: false }};
        endpoint[job.direction] = true;
        endpoints.set(target.iata, endpoint);

        if (!showRouteLabels || labeledEndpoints.has(target.iata)) continue;
        labeledEndpoints.add(target.iata);
        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("class", "route-label");
        label.setAttribute("x", end.x + 24);
        label.setAttribute("y", end.y - 24);
        label.textContent = `${{target.iata}} ${{target.shortName}}`;
        routeLayer.appendChild(label);
      }}

      for (const endpoint of endpoints.values()) {{
        const p = airportScreen(endpoint.airport);
        const point = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        const directionClass = endpoint.outgoing && endpoint.incoming
          ? "both"
          : endpoint.outgoing ? "outgoing" : "incoming";
        point.setAttribute("class", `route-endpoint ${{directionClass}}`);
        point.setAttribute("cx", p.x);
        point.setAttribute("cy", p.y);
        point.setAttribute("r", Math.max(12, (classRadius[endpoint.airport.cls] || 18) * 0.62));
        routeLayer.appendChild(point);
      }}
    }}

    function selectedFilterName(filter) {{
      return {{
        all: "全部民用运输机场",
        branch: "支线/中小型机场",
        major: "干线/枢纽机场",
        "4D": "4D 机场",
        "4C": "4C 机场",
        "3C": "3C 机场",
        "1B": "1B 机场"
      }}[filter] || "机场";
    }}

    function renderList(items) {{
      const scopeName = activeClasses.has("all")
        ? selectedFilterName("all")
        : [...activeClasses].map(selectedFilterName).join(" + ");
      resultMeta.textContent = `${{scopeName}}：显示 ${{items.length}} 个`;
      const topItems = items
        .sort((a, b) => (a.branch === b.branch ? a.iata.localeCompare(b.iata) : Number(b.branch) - Number(a.branch)));
      list.replaceChildren();
      for (const a of topItems) {{
        const btn = document.createElement("button");
        btn.className = "item" + (selected && selected.iata === a.iata ? " selected" : "");
        btn.innerHTML = `
          <span class="code" style="background:${{a.branch ? classColor[a.cls] : "#9faab4"}}">${{a.iata}}</span>
          <span>
            <span class="name">${{a.shortName}}</span>
            <span class="meta">${{a.cls}} · ${{a.city}} · ${{a.icao}}</span>
          </span>`;
        btn.addEventListener("click", () => selectAirport(a, true));
        list.appendChild(btn);
      }}
    }}

    function selectAirport(a, fly) {{
      selected = a;
      const groups = routeGroups(a);
      const routeEvidenceText = route => {{
        if (route.conditions && route.conditions.length) return route.conditions.join("；");
        if (route.flightNos && route.flightNos.length) return `${{route.flightNos.join("、")}}；班期未标注`;
        if (route.sourceLevel === "published") return "已列入公开航点表，班期未标注";
        return "历史/补充线路，班期未标注";
      }};
      const routeItemText = (route, airport) => {{
        const flightText = route.flightNos && route.flightNos.length ? `｜${{route.flightNos.join("、")}}` : "";
        return `${{airport.iata}} ${{airport.shortName}}（${{routeEvidenceText(route)}}${{flightText}}）`;
      }};
      const outgoing = groups.outgoing
        .map(route => ({{ route, airport: airportsByIata.get(route.to) }}))
        .filter(item => item.airport)
        .sort((left, right) => left.airport.iata.localeCompare(right.airport.iata));
      const incoming = groups.incoming
        .map(route => ({{ route, airport: airportsByIata.get(route.from) }}))
        .filter(item => item.airport)
        .sort((left, right) => left.airport.iata.localeCompare(right.airport.iata));
      const outgoingText = outgoing.map(item => routeItemText(item.route, item.airport)).join("、") || "暂无已录入出发航线";
      const incomingText = incoming.map(item => routeItemText(item.route, item.airport)).join("、") || "暂无已录入进入航线";
      const knownCount = [...groups.outgoing, ...groups.incoming].filter(route => route.conditionKnown).length;
      const routeSummary = `
        <span class="route-key"><i class="route-swatch" style="background:#176fb3"></i>出发 ${{outgoing.length}} 条</span>
        <span class="route-key"><i class="route-swatch" style="background:#d47a1f"></i>进入 ${{incoming.length}} 条</span><br>
        <div class="route-note">优先显示 FlightConnections 当前直飞；季节性月份来自其当前航线图。虚线为历史公开表或人工补充兜底。已识别条件 ${{knownCount}} 条。</div>
        出发航线：${{outgoingText}}<br>
        进入航线：${{incomingText}}`;
      detail.innerHTML = `<strong>${{a.iata}} ${{a.name}}</strong><br>
        ICAO：${{a.icao}}　等级：${{a.cls}}　性质：${{a.type}}<br>
        服务城市：${{a.city}}<br>
        坐标：${{a.lat.toFixed(5)}}, ${{a.lon.toFixed(5)}}　启用：${{a.opened}}<br>
        ${{routeSummary}}`;
      if (fly) {{
        const targetK = Math.max(transform.k, fitTransform.k * 2.2);
        setTransform({{
          k: targetK,
          x: SVG_W / 2 - a.x * targetK,
          y: SVG_H / 2 - a.y * targetK
        }});
      }} else {{
        drawAirports();
      }}
    }}

    function lonLatToCanvas(lon, lat) {{
      let nearest = null;
      let best = Infinity;
      for (const a of AIRPORTS) {{
        const d = Math.hypot(a.lon - lon, a.lat - lat);
        if (d < best) {{ best = d; nearest = a; }}
      }}
      return nearest ? {{ x: nearest.x, y: nearest.y }} : {{ x: SVG_W / 2, y: SVG_H / 2 }};
    }}

    function nearestAirportAt(point) {{
      let nearest = null;
      let best = Infinity;
      for (const airport of visibleAirports()) {{
        const p = airportScreen(airport);
        const distance = Math.hypot(p.x - point.x, p.y - point.y);
        const hitRadius = Math.max(90, (classRadius[airport.cls] || 18) + 55);
        if (distance <= hitRadius && distance < best) {{
          nearest = airport;
          best = distance;
        }}
      }}
      return nearest;
    }}

    for (const region of REGIONS) {{
      const btn = document.createElement("button");
      btn.className = "region-btn";
      btn.textContent = region.name;
      btn.title = region.name;
      btn.addEventListener("click", () => {{
        const [minLon, minLat, maxLon, maxLat] = region.extent;
        const nw = lonLatToCanvas(minLon, maxLat);
        const se = lonLatToCanvas(maxLon, minLat);
        const w = Math.abs(se.x - nw.x) || SVG_W * 0.3;
        const h = Math.abs(se.y - nw.y) || SVG_H * 0.3;
        const k = Math.max(1, Math.min(5.2, Math.min(SVG_W * 0.76 / w, SVG_H * 0.74 / h)));
        const cx = (nw.x + se.x) / 2;
        const cy = (nw.y + se.y) / 2;
        setTransform({{ k, x: SVG_W / 2 - cx * k, y: SVG_H / 2 - cy * k }});
      }});
      regionBox.appendChild(btn);
    }}

    svg.addEventListener("pointerdown", event => {{
      dragging = true;
      dragMoved = false;
      lastPoint = svgPoint(event);
      pointerDownPoint = lastPoint;
      svg.classList.add("dragging");
      svg.setPointerCapture(event.pointerId);
    }});
    svg.addEventListener("pointermove", event => {{
      if (!dragging) return;
      const p = svgPoint(event);
      if (pointerDownPoint && Math.hypot(p.x - pointerDownPoint.x, p.y - pointerDownPoint.y) > 35) {{
        dragMoved = true;
      }}
      setTransform({{ k: transform.k, x: transform.x + p.x - lastPoint.x, y: transform.y + p.y - lastPoint.y }});
      lastPoint = p;
    }});
    svg.addEventListener("pointerup", event => {{
      const p = svgPoint(event);
      dragging = false;
      svg.classList.remove("dragging");
      svg.releasePointerCapture(event.pointerId);
      if (!dragMoved) {{
        const airport = nearestAirportAt(p);
        if (airport) selectAirport(airport, false);
      }}
      pointerDownPoint = null;
    }});
    svg.addEventListener("wheel", event => {{
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.13 : 0.885;
      zoomAt(svgPoint(event), transform.k * factor);
    }}, {{ passive: false }});

    slider.addEventListener("input", () => zoomAt({{ x: SVG_W / 2, y: SVG_H / 2 }}, Number(slider.value)));
    labelSlider.addEventListener("input", () => {{
      labelScale = Number(labelSlider.value);
      labelReadout.textContent = `${{labelScale.toFixed(2)}}×`;
      drawAirports();
    }});
    hideLabels.addEventListener("change", drawAirports);
    document.getElementById("zoomIn").addEventListener("click", () => zoomAt({{ x: SVG_W / 2, y: SVG_H / 2 }}, transform.k * 1.22));
    document.getElementById("zoomOut").addEventListener("click", () => zoomAt({{ x: SVG_W / 2, y: SVG_H / 2 }}, transform.k / 1.22));
    document.getElementById("fitMap").addEventListener("click", () => fitMap(true));
    document.getElementById("labelUp").addEventListener("click", () => {{
      labelSlider.value = Math.min(2.2, labelScale * 1.15).toFixed(2);
      labelSlider.dispatchEvent(new Event("input"));
    }});
    document.getElementById("labelDown").addEventListener("click", () => {{
      labelSlider.value = Math.max(0.45, labelScale / 1.15).toFixed(2);
      labelSlider.dispatchEvent(new Event("input"));
    }});
    search.addEventListener("input", drawAirports);

    function syncFilterButtons() {{
      chips.forEach(chip => {{
        const active = activeClasses.has(chip.dataset.class);
        chip.classList.toggle("active", active);
        chip.setAttribute("aria-pressed", active ? "true" : "false");
      }});
    }}

    chips.forEach(chip => chip.addEventListener("click", () => {{
      const filter = chip.dataset.class;
      if (filter === "all") {{
        activeClasses = new Set(["all"]);
      }} else {{
        activeClasses.delete("all");
        if (activeClasses.has(filter)) {{
          activeClasses.delete(filter);
        }} else {{
          activeClasses.add(filter);
        }}
        if (activeClasses.size === 0) activeClasses.add("all");
      }}
      syncFilterButtons();
      drawAirports();
    }}));

    window.addEventListener("resize", syncViewportSize);
    window.addEventListener("orientationchange", syncViewportSize);
    document.addEventListener("fullscreenchange", () => {{
      syncViewportSize();
      requestAnimationFrame(fitMap);
    }});

    syncViewportSize();
    fitMap();
  </script>
</body>
</html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"wrote {OUT_HTML}")


if __name__ == "__main__":
    main()
