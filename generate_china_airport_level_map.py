import csv
import json
import math
import re
from datetime import date
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
AIRPORT_HTML = ROOT / "china_airports_wiki.html"
PROVINCES_GEOJSON = ROOT / "china_provinces.geojson"
OURAIRPORTS_CSV = Path("/private/tmp/ourairports_airports.csv")

OUT_PNG = ROOT / "china_all_operating_transport_airports_level_map_2026-06.png"
OUT_CSV = ROOT / "china_all_operating_transport_airports_level_map_2026-06.csv"

AS_OF = date(2026, 6, 24)

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"

CLASS_STYLE = {
    "4F": {"color": (183, 34, 45), "radius": 16, "label": "4F 大型/洲际枢纽"},
    "4E": {"color": (230, 118, 33), "radius": 12, "label": "4E 干线/区域枢纽"},
    "4D": {"color": (236, 178, 58), "radius": 9, "label": "4D 中型机场"},
    "4C": {"color": (35, 119, 184), "radius": 6, "label": "4C 支线/中小型"},
    "3C": {"color": (88, 151, 105), "radius": 5, "label": "3C 小型支线"},
    "1B": {"color": (120, 130, 143), "radius": 4, "label": "1B 岛屿/小型"},
}


def load_font(path, size):
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def airport_name_cn(value):
    return re.match(r"([^A-Za-z\[]+)", str(value)).group(1).strip()


def parse_airports():
    rows = []
    for table in pd.read_html(AIRPORT_HTML)[2:33]:
        for _, row in table.iterrows():
            raw_date = str(row["启用日期"])
            match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw_date)
            if not match:
                continue
            opened = date(*map(int, match.groups()))
            if opened > AS_OF:
                continue

            icao = str(row["ICAO"]).strip()
            iata = str(row["IATA"]).strip()
            if icao in {"-", "nan"} or iata in {"-", "nan"}:
                continue

            rows.append(
                {
                    "name": airport_name_cn(row["机场名称"]),
                    "icao": icao,
                    "iata": iata,
                    "opened": opened.isoformat(),
                    "flight_area_class": str(row["指标"]).strip(),
                    "type": str(row["性质"]).strip(),
                    "city": str(row["主服务城市"]).strip(),
                }
            )
    return rows


def load_coordinates():
    coords = {}
    with OURAIRPORTS_CSV.open(newline="", encoding="utf-8") as handle:
        for rec in csv.DictReader(handle):
            if rec.get("iso_country") != "CN":
                continue
            lat = rec.get("latitude_deg")
            lon = rec.get("longitude_deg")
            if not lat or not lon:
                continue
            normalized = {
                "lat": float(lat),
                "lon": float(lon),
                "source_name": rec.get("name", ""),
            }
            if rec.get("ident"):
                coords[rec["ident"].strip()] = normalized
            if rec.get("iata_code"):
                coords[rec["iata_code"].strip()] = normalized

    # Two airport records are newer or absent in OurAirports at generation time.
    coords["ZJYX"] = {"lat": 16.83278, "lon": 112.34444, "source_name": "Sansha Yongxing Airport"}
    coords["XYI"] = coords["ZJYX"]
    coords["ZWLT"] = {"lat": 41.59417, "lon": 84.29250, "source_name": "Bayinguoleng Luntai Airport"}
    coords["LTJ"] = coords["ZWLT"]
    return coords


def albers_project(lon, lat):
    # China-focused Albers equal-area projection.
    phi = math.radians(lat)
    lam = math.radians(lon)
    phi0 = math.radians(0)
    lam0 = math.radians(105)
    phi1 = math.radians(25)
    phi2 = math.radians(47)

    n = 0.5 * (math.sin(phi1) + math.sin(phi2))
    c = math.cos(phi1) ** 2 + 2 * n * math.sin(phi1)
    theta = n * (lam - lam0)
    rho = math.sqrt(max(0, c - 2 * n * math.sin(phi))) / n
    rho0 = math.sqrt(max(0, c - 2 * n * math.sin(phi0))) / n
    return rho * math.sin(theta), rho0 - rho * math.cos(theta)


def iter_polygon_rings(geometry):
    if geometry["type"] == "Polygon":
        for ring in geometry["coordinates"]:
            yield ring
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            for ring in polygon:
                yield ring


def collect_projected_features(airports):
    features = json.loads(PROVINCES_GEOJSON.read_text(encoding="utf-8"))["features"]
    projected_rings = []
    xs, ys = [], []

    for feature in features:
        rings = []
        for ring in iter_polygon_rings(feature["geometry"]):
            projected = [albers_project(lon, lat) for lon, lat in ring]
            if len(projected) >= 3:
                rings.append(projected)
                for x, y in projected:
                    xs.append(x)
                    ys.append(y)
        projected_rings.append(rings)

    for airport in airports:
        x, y = albers_project(airport["lon"], airport["lat"])
        airport["px_raw"] = x
        airport["py_raw"] = y
        xs.append(x)
        ys.append(y)

    return projected_rings, min(xs), max(xs), min(ys), max(ys)


def draw_circle(draw, x, y, r, fill, outline=(255, 255, 255), width=2):
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=outline, width=width)


def main():
    coords = load_coordinates()
    airports = []
    missing = []
    for airport in parse_airports():
        coord = coords.get(airport["icao"]) or coords.get(airport["iata"])
        if not coord:
            missing.append(airport)
            continue
        airport.update(coord)
        airports.append(airport)

    if missing:
        raise RuntimeError(f"Missing coordinates: {missing}")

    projected_rings, min_x, max_x, min_y, max_y = collect_projected_features(airports)

    width, height = 5200, 3600
    margin_left, margin_right = 280, 300
    margin_top, margin_bottom = 330, 320
    scale = min(
        (width - margin_left - margin_right) / (max_x - min_x),
        (height - margin_top - margin_bottom) / (max_y - min_y),
    )

    def to_canvas(point):
        x, y = point
        return (
            margin_left + (x - min_x) * scale,
            margin_top + (max_y - y) * scale,
        )

    image = Image.new("RGB", (width, height), (245, 248, 250))
    draw = ImageDraw.Draw(image)

    title_font = load_font(FONT_BOLD, 76)
    subtitle_font = load_font(FONT_REGULAR, 34)
    label_font = load_font(FONT_BOLD, 26)
    small_font = load_font(FONT_REGULAR, 24)
    legend_font = load_font(FONT_REGULAR, 30)
    legend_bold = load_font(FONT_BOLD, 32)

    draw.text((260, 95), "中国大陆在运营民用运输机场分布图", fill=(20, 36, 52), font=title_font)
    draw.text(
        (264, 190),
        "截至 2026-06-24；全部机场按飞行区等级标记，点越大/颜色越暖表示等级越高",
        fill=(79, 94, 109),
        font=subtitle_font,
    )

    # Province base map.
    for rings in projected_rings:
        for idx, ring in enumerate(rings):
            points = [to_canvas(point) for point in ring]
            fill = (226, 234, 239) if idx == 0 else (245, 248, 250)
            draw.polygon(points, fill=fill)
            draw.line(points + [points[0]], fill=(174, 188, 199), width=2)

    # Draw lower classes first, then larger hubs.
    order = {"1B": 1, "3C": 2, "4C": 3, "4D": 4, "4E": 5, "4F": 6}
    for airport in sorted(airports, key=lambda item: order.get(item["flight_area_class"], 0)):
        x, y = to_canvas((airport["px_raw"], airport["py_raw"]))
        airport["x"] = round(x, 1)
        airport["y"] = round(y, 1)
        style = CLASS_STYLE.get(airport["flight_area_class"], CLASS_STYLE["4C"])
        r = style["radius"]
        # Soft halo improves visibility over dense eastern China.
        draw_circle(draw, x, y, r + 3, (255, 255, 255), outline=(255, 255, 255), width=1)
        draw_circle(draw, x, y, r, style["color"], outline=(255, 255, 255), width=2)

    # Label the highest-grade airports only to keep all points visible.
    label_offsets = [
        (18, -18),
        (18, 10),
        (-84, -18),
        (-84, 10),
        (22, -4),
        (-72, -4),
    ]
    label_i = 0
    for airport in airports:
        if airport["flight_area_class"] not in {"4F", "4E"}:
            continue
        x, y = airport["x"], airport["y"]
        dx, dy = label_offsets[label_i % len(label_offsets)]
        label_i += 1
        label = airport["iata"]
        bbox = draw.textbbox((x + dx, y + dy), label, font=label_font)
        pad = 5
        draw.rounded_rectangle(
            (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
            radius=6,
            fill=(255, 255, 255),
            outline=(198, 207, 216),
            width=1,
        )
        draw.text((x + dx, y + dy), label, fill=(32, 45, 58), font=label_font)

    counts = {}
    for airport in airports:
        counts[airport["flight_area_class"]] = counts.get(airport["flight_area_class"], 0) + 1

    legend_x, legend_y = 275, 2870
    draw.rounded_rectangle(
        (legend_x - 25, legend_y - 28, legend_x + 1450, legend_y + 305),
        radius=14,
        fill=(255, 255, 255),
        outline=(205, 215, 224),
        width=2,
    )
    draw.text((legend_x, legend_y), f"机场等级图例  共 {len(airports)} 座", fill=(25, 39, 53), font=legend_bold)
    y = legend_y + 58
    for cls in ["4F", "4E", "4D", "4C", "3C", "1B"]:
        style = CLASS_STYLE[cls]
        draw_circle(draw, legend_x + 22, y + 18, style["radius"], style["color"], outline=(255, 255, 255), width=2)
        draw.text(
            (legend_x + 62, y),
            f"{style['label']}：{counts.get(cls, 0)} 座",
            fill=(55, 70, 84),
            font=legend_font,
        )
        y += 42

    source = (
        "底图：中国省级行政区 GeoJSON；机场清单：中华人民共和国机场列表本地快照；"
        "坐标：OurAirports，XYI/LTJ 使用公开百科坐标补齐。"
    )
    draw.text((275, 3460), source, fill=(95, 108, 120), font=small_font)
    draw.text(
        (3860, 3460),
        "注：不含港澳台机场；未标未来建设/迁建/选址批复机场。",
        fill=(95, 108, 120),
        font=small_font,
    )

    image.save(OUT_PNG, quality=95)

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "iata",
                "icao",
                "flight_area_class",
                "type",
                "city",
                "opened",
                "lat",
                "lon",
                "source_name",
            ],
        )
        writer.writeheader()
        for airport in sorted(airports, key=lambda item: (item["flight_area_class"], item["iata"])):
            writer.writerow({key: airport.get(key, "") for key in writer.fieldnames})

    print(f"wrote {OUT_PNG}")
    print(f"wrote {OUT_CSV}")
    print("counts", counts)


if __name__ == "__main__":
    main()
