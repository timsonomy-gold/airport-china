import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const ROOT = process.cwd();
const MAP_HTML = path.join(ROOT, "china_branch_airports_interactive_2026-06.html");
const OUT_JSON = path.join(ROOT, "china_current_routes_flightconnections_2026-06.json");
const CACHE_JSON = path.join(ROOT, "flightconnections_airport_ids_2026-06.json");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function parseArgs() {
  const args = new Map();
  for (const raw of process.argv.slice(2)) {
    const [key, value = "true"] = raw.replace(/^--/, "").split("=");
    args.set(key, value);
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadAirports() {
  const html = await fs.readFile(MAP_HTML, "utf8");
  const match = html.match(/const AIRPORTS = ([\s\S]*?);\n/);
  if (!match) throw new Error(`Cannot find AIRPORTS payload in ${MAP_HTML}`);
  return JSON.parse(match[1]);
}

function monthsFromMask(mask) {
  const months = ["4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "1月", "2月", "3月"];
  return months.filter((_, index) => mask & (1 << index));
}

function compactMonths(mask) {
  if (!mask || mask === 4095) return mask === 4095 ? "全年/常年直飞" : "月份未标注";
  const months = monthsFromMask(mask);
  if (!months.length) return "月份未标注";
  return `季节性：${months.join("、")}`;
}

async function readJsonIfExists(file, fallback) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return fallback;
  }
}

async function main() {
  const args = parseArgs();
  const airports = await loadAirports();
  let selectedAirports = airports;
  if (args.has("codes")) {
    const codes = new Set(args.get("codes").split(",").map((code) => code.trim().toUpperCase()).filter(Boolean));
    selectedAirports = airports.filter((airport) => codes.has(airport.iata));
  } else if (args.has("failed-only")) {
    const previous = await readJsonIfExists(OUT_JSON, { failures: [] });
    const codes = new Set((previous.failures || []).map((failure) => failure.iata));
    selectedAirports = airports.filter((airport) => codes.has(airport.iata));
  }
  const delayMs = Number(args.get("delay-ms") || 250);
  const airportCodes = new Set(airports.map((airport) => airport.iata).filter(Boolean));
  const idCache = await readJsonIfExists(CACHE_JSON, {});
  const previous = args.has("replace")
    ? { routes: [], failures: [] }
    : await readJsonIfExists(OUT_JSON, { routes: [], failures: [] });
  const selectedCodes = new Set(selectedAirports.map((airport) => airport.iata));
  const routeMap = new Map(
    (previous.routes || [])
      .filter((route) => !selectedCodes.has(route.from))
      .map((route) => [`${route.from}-${route.to}`, route]),
  );
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto("https://www.flightconnections.com/", { waitUntil: "domcontentloaded", timeout: 30000 });

  const routes = [];
  const failures = [];
  const startedAt = new Date().toISOString();

  for (const [index, airport] of selectedAirports.entries()) {
    const code = airport.iata;
    if (!code) continue;
    try {
      let airportInfo = idCache[code];
      if (!airportInfo?.c) {
        airportInfo = await page.evaluate(async (iata) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 12000);
          const response = await fetch(`/airports_url.php?lang=en&iata=${iata.toLowerCase()}`, { signal: controller.signal });
          clearTimeout(timer);
          if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
          const text = await response.text();
          const id = text.match(/"c"\s*:\s*(\d+)/)?.[1];
          const label = text.match(/"a"\s*:\s*"([^"]+)"/)?.[1] || "";
          if (!id) return null;
          return { a: label, c: Number(id) };
        }, code);
        if (!airportInfo?.c) throw new Error("not listed by FlightConnections");
        idCache[code] = airportInfo;
        if (index % 20 === 0) await fs.writeFile(CACHE_JSON, JSON.stringify(idCache, null, 2), "utf8");
      }

      const routeData = await page.evaluate(async (airportId) => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 12000);
        const query = [
          `v=1097`,
          `lang=en`,
          `f=no0`,
          `direction=from`,
          `exc=`,
          `ids=`,
          `cl=`,
          `flight_direction=from`,
          `flight_type=round`,
          `airlines=`,
          `alliance=`,
          `classes=`,
          `dates=`,
          `dates_type=`,
          `days_in_destination=`,
          `aircrafts=`,
          `dep_time_min=`,
          `dep_time_max=`,
          `arr_time_min=`,
          `arr_time_max=`,
          `dis_min=`,
          `dis_max=`,
          `dur_min=`,
          `dur_max=`,
        ].join("&");
        const response = await fetch(`/rt${airportId}.json?${query}`, { signal: controller.signal });
        clearTimeout(timer);
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return await response.json();
      }, airportInfo.c);

      for (const [routeIndex, row] of (routeData.lst || []).entries()) {
        const target = row[0];
        if (!airportCodes.has(target) || target === code) continue;
        const monthMask = Number(routeData.mths?.[routeIndex + 1] || 0);
        const route = {
          from: code,
          to: target,
          durationMin: Number(row[4] || 0),
          distanceMiles: Number(row[5] || 0),
          conditions: [compactMonths(monthMask), "具体星期/日期以购票平台实时排班为准"].filter(Boolean),
          monthMask,
          source: "FlightConnections",
          sourceLevel: "current",
          retrievedAt: startedAt.slice(0, 10),
        };
        routes.push(route);
        routeMap.set(`${route.from}-${route.to}`, route);
      }

      if ((index + 1) % 10 === 0) {
        console.log(`${index + 1}/${selectedAirports.length} airports, ${routes.length} new routes`);
      }
    } catch (error) {
      failures.push({ iata: code, name: airport.name, error: String(error.message || error) });
    }
    if (delayMs) await sleep(delayMs);
  }

  await fs.writeFile(CACHE_JSON, JSON.stringify(idCache, null, 2), "utf8");
  await fs.writeFile(
    OUT_JSON,
    JSON.stringify(
      {
        generatedAt: startedAt,
        source: "FlightConnections",
        routes: [...routeMap.values()].sort((left, right) => `${left.from}-${left.to}`.localeCompare(`${right.from}-${right.to}`)),
        failures: [
          ...(previous.failures || []).filter((failure) => !selectedCodes.has(failure.iata)),
          ...failures,
        ],
      },
      null,
      2,
    ),
    "utf8",
  );
  await browser.close();

  const finalRoutes = [...routeMap.values()];
  const covered = new Set(finalRoutes.flatMap((route) => [route.from, route.to]));
  console.log(`wrote ${OUT_JSON}`);
  console.log(`routes: ${finalRoutes.length}`);
  console.log(`covered airports: ${covered.size}/${airports.length}`);
  console.log(`failures: ${failures.length}`);
  if (failures.length) console.log(failures.slice(0, 20));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
