import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import generate_china_airport_level_map as base


ROOT = Path(__file__).resolve().parent
OUT_ATLAS = ROOT / "china_branch_airports_labeled_atlas_2026-06.png"
OUT_DIR = ROOT / "china_branch_airport_region_maps_2026-06"
OUT_CSV = ROOT / "china_branch_airports_labeled_2026-06.csv"

FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"

BRANCH_CLASSES = {"4D", "4C", "3C", "1B"}

CLASS_STYLE = {
    "4D": {"color": (218, 159, 47), "radius": 8, "label": "4D 中型/旅游支线"},
    "4C": {"color": (35, 119, 184), "radius": 6, "label": "4C 支线"},
    "3C": {"color": (88, 151, 105), "radius": 5, "label": "3C 小型支线"},
    "1B": {"color": (120, 130, 143), "radius": 5, "label": "1B 小型机场"},
    "major": {"color": (168, 177, 186), "radius": 5, "label": "4E/4F 参考点"},
}

REGIONS = [
    {
        "name": "新疆 / 河西 / 西蒙",
        "slug": "01_xinjiang_hexi_west_inner_mongolia",
        "extent": (72.0, 35.0, 107.5, 50.5),
    },
    {
        "name": "青藏 / 川西 / 甘青宁",
        "slug": "02_qinghai_tibet_west_sichuan",
        "extent": (78.0, 26.5, 107.0, 39.8),
    },
    {
        "name": "东北 / 蒙东",
        "slug": "03_northeast_east_inner_mongolia",
        "extent": (108.0, 38.0, 135.5, 54.2),
    },
    {
        "name": "华北 / 华中 / 黄淮",
        "slug": "04_north_central_china",
        "extent": (104.0, 29.0, 123.5, 42.8),
    },
    {
        "name": "西南 / 云贵川渝桂西",
        "slug": "05_southwest",
        "extent": (96.0, 20.5, 111.5, 34.5),
    },
    {
        "name": "华东 / 华南 / 海岛",
        "slug": "06_east_south_china",
        "extent": (108.0, 13.6, 124.5, 33.0),
    },
]


def load_font(path, size):
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def load_airports():
    coords = base.load_coordinates()
    airports = []
    for airport in base.parse_airports():
        coord = coords.get(airport["icao"]) or coords.get(airport["iata"])
        if not coord:
            continue
        airport.update(coord)
        airport["short_name"] = shorten_name(airport["name"])
        airport["is_branch"] = airport["flight_area_class"] in BRANCH_CLASSES
        airports.append(airport)
    return airports


def shorten_name(name):
    result = name
    for suffix in [
        "国际机场",
        "机场",
    ]:
        if result.endswith(suffix):
            result = result[: -len(suffix)]
    result = result.replace("国际", "")
    replacements = {
        "呼伦贝尔海拉尔": "海拉尔",
        "二连浩特赛乌素": "二连浩特",
        "乌兰浩特义勒力特": "乌兰浩特",
        "阿尔山伊尔施": "阿尔山",
        "巴彦淖尔天吉泰": "巴彦淖尔",
        "乌兰察布集宁": "乌兰察布",
        "阿拉善左旗巴彦浩特": "阿左旗",
        "阿拉善右旗巴丹吉林": "阿右旗",
        "额济纳旗桃来": "额济纳旗",
        "布尔津喀纳斯": "喀纳斯",
        "富蕴可可托海": "富蕴",
        "塔什库尔干红其拉甫": "塔什库尔干",
        "巴音郭楞轮台": "轮台",
        "和静巴音布鲁克": "巴音布鲁克",
        "大兴安岭鄂伦春": "鄂伦春",
        "五大连池德都": "五大连池",
        "抚远东极": "抚远",
        "佳木斯松江": "佳木斯",
        "建三江湿地": "建三江",
        "牡丹江海浪": "牡丹江",
        "绥芬河东宁": "绥芬河",
        "黔东南黎平": "黎平",
        "铜仁凤凰": "铜仁",
        "铜仁德江": "德江",
        "西双版纳嘎洒": "西双版纳",
        "德宏芒市": "芒市",
        "迪庆香格里拉": "香格里拉",
        "甘孜格萨尔": "甘孜格萨尔",
        "甘孜康定": "康定",
        "稻城亚丁": "稻城亚丁",
        "阿坝红原": "红原",
        "九寨黄龙": "九寨黄龙",
        "三沙永兴": "三沙永兴",
    }
    return replacements.get(result, result)


def lonlat_in_extent(lon, lat, extent):
    min_lon, min_lat, max_lon, max_lat = extent
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def projected_extent(extent):
    min_lon, min_lat, max_lon, max_lat = extent
    samples = []
    steps = 12
    for i in range(steps + 1):
        lon = min_lon + (max_lon - min_lon) * i / steps
        samples.append(base.albers_project(lon, min_lat))
        samples.append(base.albers_project(lon, max_lat))
    for i in range(steps + 1):
        lat = min_lat + (max_lat - min_lat) * i / steps
        samples.append(base.albers_project(min_lon, lat))
        samples.append(base.albers_project(max_lon, lat))
    xs = [p[0] for p in samples]
    ys = [p[1] for p in samples]
    return min(xs), max(xs), min(ys), max(ys)


def iter_projected_rings():
    features = base.json.loads(base.PROVINCES_GEOJSON.read_text(encoding="utf-8"))["features"]
    for feature in features:
        for ring in base.iter_polygon_rings(feature["geometry"]):
            if len(ring) >= 3:
                yield [base.albers_project(lon, lat) for lon, lat in ring]


def make_mapper(extent, width, height, margins):
    min_x, max_x, min_y, max_y = projected_extent(extent)
    left, top, right, bottom = margins
    scale = min((width - left - right) / (max_x - min_x), (height - top - bottom) / (max_y - min_y))

    def to_canvas(lon, lat):
        x, y = base.albers_project(lon, lat)
        return left + (x - min_x) * scale, top + (max_y - y) * scale

    def raw_to_canvas(x, y):
        return left + (x - min_x) * scale, top + (max_y - y) * scale

    return to_canvas, raw_to_canvas


def draw_base_map(draw, raw_to_canvas, width, height):
    draw.rectangle((0, 0, width, height), fill=(246, 249, 251))
    for ring in iter_projected_rings():
        points = [raw_to_canvas(x, y) for x, y in ring]
        draw.polygon(points, fill=(228, 236, 241))
        draw.line(points + [points[0]], fill=(181, 195, 206), width=2)


def circle(draw, x, y, r, fill, outline=(255, 255, 255), width=2):
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=outline, width=width)


def rect_overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def place_label(draw, text, x, y, font, occupied, panel_size):
    width, height = panel_size
    offsets = [
        (13, -34),
        (13, 10),
        (-13, -34),
        (-13, 10),
        (18, -12),
        (-18, -12),
        (0, -50),
        (0, 28),
        (30, -46),
        (-30, -46),
        (30, 28),
        (-30, 28),
    ]
    candidates = []
    for dx, dy in offsets:
        bbox = draw.textbbox((x + dx, y + dy), text, font=font)
        pad_x, pad_y = 6, 4
        rect = (bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y)
        out_penalty = 0
        if rect[0] < 16:
            out_penalty += 16 - rect[0]
        if rect[1] < 70:
            out_penalty += 70 - rect[1]
        if rect[2] > width - 16:
            out_penalty += rect[2] - (width - 16)
        bottom_limit = height - 205
        if rect[3] > bottom_limit:
            out_penalty += rect[3] - bottom_limit
        overlaps = sum(1 for item in occupied if rect_overlap(rect, item))
        distance = math.hypot(dx, dy)
        candidates.append((overlaps * 10000 + out_penalty * 100 + distance, rect, (x + dx, y + dy)))
    _, rect, pos = min(candidates, key=lambda item: item[0])
    occupied.append(rect)
    return rect, pos


def draw_region(region, airports, width=3300, height=2250, include_footer=True):
    image = Image.new("RGB", (width, height), (246, 249, 251))
    draw = ImageDraw.Draw(image)

    title_font = load_font(FONT_BOLD, 48)
    subtitle_font = load_font(FONT_REGULAR, 26)
    label_font = load_font(FONT_BOLD, 25)
    small_font = load_font(FONT_REGULAR, 22)
    legend_font = load_font(FONT_REGULAR, 24)

    to_canvas, raw_to_canvas = make_mapper(region["extent"], width, height, (90, 130, 90, 100))
    draw_base_map(draw, raw_to_canvas, width, height)

    draw.text((70, 38), region["name"], fill=(24, 39, 54), font=title_font)
    draw.text((72, 94), "标注 4D/4C/3C/1B；灰点为 4E/4F 参考机场", fill=(83, 98, 111), font=subtitle_font)

    branch = [a for a in airports if a["is_branch"] and lonlat_in_extent(a["lon"], a["lat"], region["extent"])]
    major = [a for a in airports if not a["is_branch"] and lonlat_in_extent(a["lon"], a["lat"], region["extent"])]

    for airport in major:
        x, y = to_canvas(airport["lon"], airport["lat"])
        circle(draw, x, y, CLASS_STYLE["major"]["radius"], CLASS_STYLE["major"]["color"], width=1)

    order = {"1B": 1, "3C": 2, "4C": 3, "4D": 4}
    for airport in sorted(branch, key=lambda item: order[item["flight_area_class"]]):
        x, y = to_canvas(airport["lon"], airport["lat"])
        style = CLASS_STYLE[airport["flight_area_class"]]
        circle(draw, x, y, style["radius"] + 3, (255, 255, 255), outline=(255, 255, 255), width=1)
        circle(draw, x, y, style["radius"], style["color"], width=2)
        airport[f"{region['slug']}_x"] = round(x, 1)
        airport[f"{region['slug']}_y"] = round(y, 1)

    occupied = []
    # Larger airports first get better label positions.
    for airport in sorted(branch, key=lambda item: (-order[item["flight_area_class"]], item["iata"])):
        x, y = to_canvas(airport["lon"], airport["lat"])
        text = f"{airport['iata']} {airport['short_name']}"
        rect, pos = place_label(draw, text, x, y, label_font, occupied, (width, height))
        draw.line((x, y, pos[0], pos[1] + 12), fill=(116, 132, 146), width=1)
        draw.rounded_rectangle(rect, radius=6, fill=(255, 255, 255), outline=(202, 213, 222), width=1)
        draw.text(pos, text, fill=(28, 43, 57), font=label_font)

    legend_x, legend_y = 74, height - 178
    draw.rounded_rectangle(
        (legend_x - 18, legend_y - 20, legend_x + 1060, legend_y + 116),
        radius=12,
        fill=(255, 255, 255),
        outline=(204, 214, 223),
        width=2,
    )
    draw.text((legend_x, legend_y), f"本区域标注支线/中小型机场 {len(branch)} 座", fill=(38, 53, 67), font=legend_font)
    lx = legend_x
    ly = legend_y + 48
    for cls in ["4D", "4C", "3C", "1B"]:
        style = CLASS_STYLE[cls]
        count = sum(1 for item in branch if item["flight_area_class"] == cls)
        circle(draw, lx + 14, ly + 14, style["radius"], style["color"], width=2)
        draw.text((lx + 34, ly), f"{cls} {count}", fill=(72, 87, 100), font=legend_font)
        lx += 148

    if include_footer:
        draw.text(
            (width - 760, height - 48),
            "截至 2026-06-24；名称格式为 IATA + 中文短名",
            fill=(101, 115, 128),
            font=small_font,
        )

    return image, branch


def draw_overview(airports, width=6800, height=2300):
    image = Image.new("RGB", (width, height), (246, 249, 251))
    draw = ImageDraw.Draw(image)
    title_font = load_font(FONT_BOLD, 66)
    subtitle_font = load_font(FONT_REGULAR, 30)
    legend_font = load_font(FONT_REGULAR, 27)

    all_lons = [a["lon"] for a in airports]
    all_lats = [a["lat"] for a in airports]
    extent = (min(all_lons) - 2, min(all_lats) - 1.2, max(all_lons) + 2, max(all_lats) + 1.2)
    to_canvas, raw_to_canvas = make_mapper(extent, width, height, (160, 230, 160, 180))
    draw_base_map(draw, raw_to_canvas, width, height)

    draw.text((120, 60), "中国大陆支线/中小型机场标注图集", fill=(24, 39, 54), font=title_font)
    draw.text(
        (124, 142),
        "总览展示空间关系；下方 6 个区域图按适合阅读的比例标注 4D/4C/3C/1B 机场名称",
        fill=(79, 94, 109),
        font=subtitle_font,
    )

    for airport in sorted(airports, key=lambda item: item["is_branch"]):
        x, y = to_canvas(airport["lon"], airport["lat"])
        if airport["is_branch"]:
            style = CLASS_STYLE[airport["flight_area_class"]]
            circle(draw, x, y, style["radius"], style["color"], width=2)
        else:
            circle(draw, x, y, 4, CLASS_STYLE["major"]["color"], width=1)

    legend_x, legend_y = 120, height - 245
    draw.rounded_rectangle(
        (legend_x - 22, legend_y - 22, legend_x + 1650, legend_y + 135),
        radius=12,
        fill=(255, 255, 255),
        outline=(204, 214, 223),
        width=2,
    )
    draw.text(
        (legend_x, legend_y),
        f"支线/中小型机场 {sum(1 for a in airports if a['is_branch'])} 座；4E/4F 仅作灰色参考",
        fill=(38, 53, 67),
        font=legend_font,
    )
    lx = legend_x
    ly = legend_y + 56
    for cls in ["4D", "4C", "3C", "1B"]:
        count = sum(1 for item in airports if item["flight_area_class"] == cls)
        style = CLASS_STYLE[cls]
        circle(draw, lx + 15, ly + 15, style["radius"], style["color"], width=2)
        draw.text((lx + 38, ly), f"{style['label']}：{count}", fill=(72, 87, 100), font=legend_font)
        lx += 360

    return image


def main():
    OUT_DIR.mkdir(exist_ok=True)
    airports = load_airports()
    branch_airports = [a for a in airports if a["is_branch"]]

    overview = draw_overview(airports)
    panel_images = []
    coverage = set()
    for region in REGIONS:
        image, branch = draw_region(region, airports)
        image.save(OUT_DIR / f"{region['slug']}.png", quality=95)
        panel_images.append((region, image))
        coverage.update(item["iata"] for item in branch)

    missing = sorted(set(item["iata"] for item in branch_airports) - coverage)
    if missing:
        raise RuntimeError(f"Branch airports not covered by regional panels: {missing}")

    atlas_width = 7000
    gutter = 120
    top = 120
    panel_w, panel_h = 3300, 2250
    atlas_height = top + 2300 + 130 + 3 * panel_h + 2 * gutter + 160
    atlas = Image.new("RGB", (atlas_width, atlas_height), (246, 249, 251))
    atlas.paste(overview, (100, top))
    y0 = top + 2300 + 130
    for idx, (_, image) in enumerate(panel_images):
        col = idx % 2
        row = idx // 2
        x = 100 + col * (panel_w + gutter)
        y = y0 + row * (panel_h + gutter)
        atlas.paste(image, (x, y))
    atlas.save(OUT_ATLAS, quality=95)

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "short_name",
                "iata",
                "icao",
                "flight_area_class",
                "type",
                "city",
                "opened",
                "lat",
                "lon",
            ],
        )
        writer.writeheader()
        for airport in sorted(branch_airports, key=lambda item: (item["flight_area_class"], item["iata"])):
            writer.writerow({key: airport.get(key, "") for key in writer.fieldnames})

    print(f"wrote {OUT_ATLAS}")
    print(f"wrote {OUT_DIR}")
    print(f"wrote {OUT_CSV}")
    print(f"branch airports: {len(branch_airports)}; covered: {len(coverage)}")


if __name__ == "__main__":
    main()
