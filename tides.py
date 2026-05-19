#!/usr/bin/env python3
"""ANSI Tide Chart + Conditions Dashboard — Texas Gulf Coast"""

import argparse
import urllib.request
import json
import sys
import math
import concurrent.futures
from datetime import datetime, date, timedelta

# ── ANSI codes ────────────────────────────────────────────────────────────────
RESET    = "\033[0m";  BOLD    = "\033[1m";  DIM     = "\033[2m"
BLACK    = "\033[30m"; RED     = "\033[31m"; GREEN   = "\033[32m"
YELLOW   = "\033[33m"; BLUE    = "\033[34m"; MAGENTA = "\033[35m"
CYAN     = "\033[36m"; WHITE   = "\033[37m"
BRED     = "\033[91m"; BGREEN  = "\033[92m"; BYELLOW = "\033[93m"
BBLUE    = "\033[94m"; BMAGENTA= "\033[95m"; BCYAN   = "\033[96m"
BWHITE   = "\033[97m"
BG_BLUE      = "\033[44m";  BG_CYAN      = "\033[46m"
BG_BLACK     = "\033[40m";  BG_DARK_BLUE = "\033[48;5;17m"
BG_NAVY      = "\033[48;5;18m"; BG_SEA   = "\033[48;5;24m"
BG_WATER     = "\033[48;5;27m"; BG_FOAM  = "\033[48;5;51m"

# ── Station config ────────────────────────────────────────────────────────────
STATIONS = {
    "Freeport, TX": {
        "id":     "8772440", "lat": 28.9543, "lon": -95.3677,
        "met_id": "8771341",  # Galveston Bay Entrance — nearest full met station
        "nws":    "https://api.weather.gov/points/28.9543,-95.3677",
    },
    "North Padre Island, TX": {
        "id":     "8775792", "lat": 27.5800, "lon": -97.2270,
        "met_id": "8775241",  # Aransas Pass — nearest full met station
        "nws":    "https://api.weather.gov/points/27.5800,-97.2270",
    },
}

CHART_WIDTH  = 72
CHART_HEIGHT = 20

# ── Timezone ──────────────────────────────────────────────────────────────────
def week_dates(which: str) -> tuple:
    """Return (start, end) date for this/next/last week (Mon–Sun)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if which == "next":
        monday += timedelta(weeks=1)
    elif which == "last":
        monday -= timedelta(weeks=1)
    return monday, monday + timedelta(days=6)


def central_utc_offset(d: date) -> float:
    """Return UTC offset for US Central Time (-5 CDT or -6 CST)."""
    y = d.year
    dst_start = min(
        (date(y, 3, day) for day in range(8, 15) if date(y, 3, day).weekday() == 6)
    )
    dst_end = min(
        (date(y, 11, day) for day in range(1, 8) if date(y, 11, day).weekday() == 6)
    )
    return -5.0 if dst_start <= d < dst_end else -6.0


def hhmm(decimal_hours: float) -> str:
    """Convert decimal hours to HH:MM AM/PM string."""
    h = decimal_hours % 24
    hh = int(h)
    mm = int(round((h - hh) * 60))
    if mm == 60:
        hh += 1; mm = 0
    suffix = "AM" if hh < 12 else "PM"
    hh12 = hh % 12 or 12
    return f"{hh12}:{mm:02d} {suffix}"


# ── Astronomical calculations ─────────────────────────────────────────────────
def julian_date(d: date) -> float:
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1; m += 12
    A = y // 100
    B = 2 - A + A // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + B - 1524.5


def moon_phase(d: date) -> tuple:
    """Returns (phase_name, illumination_pct, emoji)."""
    days = (julian_date(d) - 2451549.5) % 29.53058867
    illum = round((1 - math.cos(2 * math.pi * days / 29.53058867)) / 2 * 100)
    p = days / 29.53058867
    if   p < 0.0625 or p >= 0.9375: return "New Moon",        illum, "🌑"
    elif p < 0.1875:                 return "Waxing Crescent", illum, "🌒"
    elif p < 0.3125:                 return "First Quarter",   illum, "🌓"
    elif p < 0.4375:                 return "Waxing Gibbous",  illum, "🌔"
    elif p < 0.5625:                 return "Full Moon",       illum, "🌕"
    elif p < 0.6875:                 return "Waning Gibbous",  illum, "🌖"
    elif p < 0.8125:                 return "Last Quarter",    illum, "🌗"
    else:                            return "Waning Crescent", illum, "🌘"


def sun_times(d: date, lat: float, lon: float, utc_off: float) -> tuple:
    """Returns (sunrise_h, sunset_h, solar_noon_h) in local decimal hours."""
    N = d.timetuple().tm_yday
    decl_r = math.radians(-23.45 * math.cos(math.radians(360 / 365 * (N + 10))))
    B = math.radians(360 / 364 * (N - 81))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)  # minutes
    noon_utc = 12.0 - lon / 15.0 - eot / 60.0
    cos_ha = -math.tan(math.radians(lat)) * math.tan(decl_r)
    if not (-1 < cos_ha < 1):
        return None, None, noon_utc + utc_off
    ha_h = math.degrees(math.acos(cos_ha)) / 15.0
    return noon_utc - ha_h + utc_off, noon_utc + ha_h + utc_off, noon_utc + utc_off


def moon_ra(jd: float) -> float:
    """Simplified moon right ascension in degrees (~1° accuracy)."""
    d = jd - 2451545.0
    L = (218.316 + 13.176396 * d) % 360
    M = math.radians((134.963 + 13.064993 * d) % 360)
    F = math.radians((93.272  + 13.229350 * d) % 360)
    lam = (L + 6.289 * math.sin(M)
             - 1.274 * math.sin(2 * math.radians(L) - M)
             + 0.658 * math.sin(2 * math.radians(L))
             - 0.214 * math.sin(2 * M)
             - 0.114 * math.sin(2 * F)) % 360
    beta = 5.128 * math.sin(F)
    eps  = math.radians(23.439 - 0.0000004 * d)
    lr, br = math.radians(lam), math.radians(beta)
    x = math.cos(br) * math.cos(lr)
    y = math.cos(eps) * math.cos(br) * math.sin(lr) - math.sin(eps) * math.sin(br)
    return math.degrees(math.atan2(y, x)) % 360


def solunar_times(d: date, lon: float, utc_off: float) -> dict:
    """Return solunar major/minor period start times in local decimal hours."""
    jd0 = julian_date(d)
    T   = (jd0 - 2451545.0) / 36525.0
    # GMST at 0h UT in degrees
    gmst0 = (100.4606184 + 36000.77004 * T + 0.000387933 * T ** 2) % 360

    # Initial RA at noon UTC, then refine once
    ra = moon_ra(jd0 + 0.5)
    t_ut = ((ra - lon - gmst0) % 360) / (360.985647 / 24)
    ra = moon_ra(jd0 + t_ut / 24)
    t_ut = ((ra - lon - gmst0) % 360) / (360.985647 / 24)

    upper  = (t_ut + utc_off) % 24          # moon overhead — major
    lower  = (upper + 12 + 25 / 60) % 24    # moon underfoot — major
    minor1 = (upper -  6 - 12.5 / 60) % 24  # moonrise — minor
    minor2 = (upper +  6 + 12.5 / 60) % 24  # moonset  — minor
    return {"major1": upper, "major2": lower, "minor1": minor1, "minor2": minor2}


# ── Station search ────────────────────────────────────────────────────────────
_STATIONS_LIST_URL = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
    "?type=tidepredictions&units=english"
)

def search_stations(query: str) -> list:
    """Search NOAA tide-prediction stations by name or state."""
    print(f"{DIM}  Fetching NOAA station list…{RESET}", end="\r", flush=True)
    data = _get(_STATIONS_LIST_URL, timeout=15)
    print(" " * 40, end="\r")  # clear the line
    if not data or "stations" not in data:
        return []
    q = query.lower()
    matches = []
    for s in data["stations"]:
        name  = s.get("name", "")
        state = s.get("state", "")
        if q in name.lower() or q in state.lower():
            matches.append({
                "id":   s["id"],
                "name": f"{name}, {state}" if state else name,
                "lat":  float(s.get("lat", 0)),
                "lon":  float(s.get("lng", 0)),
            })
    return matches


def fetch_station_info(station_id: str) -> dict | None:
    """Fetch name + coordinates for a single NOAA station."""
    url = (f"https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/"
           f"stations/{station_id}.json")
    data = _get(url, timeout=10)
    if not data or not data.get("stations"):
        return None
    s = data["stations"][0]
    state = s.get("state", "")
    name  = s.get("name", "")
    return {
        "id":   station_id,
        "name": f"{name}, {state}" if state else name,
        "lat":  float(s.get("lat", 0)),
        "lon":  float(s.get("lng", 0)),
    }


def pick_station(query: str) -> dict | None:
    """Search and interactively pick a station; return station dict or None."""
    matches = search_stations(query)
    if not matches:
        print(f"{RED}No stations found matching '{query}'.{RESET}")
        print(f"{DIM}  Try a city name, partial name, or 2-letter state code.{RESET}")
        return None
    if len(matches) == 1:
        s = matches[0]
        print(f"{BGREEN}  Matched: {s['name']}  ({s['id']}){RESET}")
        return s

    cap = 30
    print(f"\n{BCYAN}  {len(matches)} stations match '{query}'"
          f"{' (showing first ' + str(cap) + ')' if len(matches) > cap else ''}:{RESET}\n")
    for i, m in enumerate(matches[:cap], 1):
        print(f"  {BWHITE}{i:2}.{RESET} {m['name']}  {DIM}({m['id']}){RESET}")
    if len(matches) > cap:
        print(f"  {DIM}  … and {len(matches) - cap} more — refine your query to narrow results{RESET}")
    print()
    try:
        choice = input(f"{BYELLOW}  Select station number (or q to quit): {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return None
    if choice.lower() in ("q", "quit", ""):
        return None
    try:
        idx = int(choice) - 1
        if not (0 <= idx < min(len(matches), cap)):
            raise ValueError
        return matches[idx]
    except ValueError:
        print(f"{RED}Invalid selection.{RESET}")
        return None


# ── Data fetching ─────────────────────────────────────────────────────────────
def _get(url: str, timeout: int = 10, headers: dict = None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def fetch_predictions(station_id: str, today: str, interval: str, end_date: str = None) -> list:
    end = end_date or today
    url = (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?begin_date={today}&end_date={end}&station={station_id}"
        "&product=predictions&datum=MLLW&time_zone=lst_ldt"
        f"&interval={interval}&units=english&format=json&application=ansi_tide_chart"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        print(f"{RED}Error fetching predictions: {e}{RESET}"); sys.exit(1)
    if "error" in data:
        print(f"{RED}NOAA error: {data['error'].get('message', data['error'])}{RESET}")
        sys.exit(1)
    return data.get("predictions", [])


def fetch_obs(station_id: str, product: str):
    """Fetch the latest NOAA observation for one product."""
    url = (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?station={station_id}&product={product}"
        "&date=latest&units=english&time_zone=lst_ldt&format=json"
    )
    data = _get(url)
    if not data or "data" not in data:
        return None
    try:
        return data["data"][-1]
    except (IndexError, KeyError):
        return None


def fetch_water_level_obs(station_id: str):
    """Fetch recent water level to compute deviation from prediction."""
    url = (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?station={station_id}&product=water_level&datum=MLLW"
        "&date=latest&units=english&time_zone=lst_ldt&format=json"
    )
    data = _get(url)
    if not data or "data" not in data:
        return None
    try:
        return data["data"][-1]
    except (IndexError, KeyError):
        return None


def fetch_nws(points_url: str) -> dict | None:
    """Fetch current NWS conditions and short-range forecast."""
    hdr = {"User-Agent": "tides-cli/1.0 (texas-gulf-coast-fishing-dashboard)"}
    pts = _get(points_url, timeout=8, headers=hdr)
    if not pts:
        return None
    hourly_url = pts.get("properties", {}).get("forecastHourly")
    forecast_url = pts.get("properties", {}).get("forecast")
    result = {}
    if hourly_url:
        hly = _get(hourly_url, timeout=8, headers=hdr)
        if hly:
            result["hourly"] = hly.get("properties", {}).get("periods", [])[:3]
    if forecast_url:
        fc = _get(forecast_url, timeout=8, headers=hdr)
        if fc:
            result["forecast"] = fc.get("properties", {}).get("periods", [])[:2]
    return result or None


def fetch_all_obs(tide_id: str, met_id: str) -> dict:
    """Fetch all NOAA observations in parallel.
    Met products (wind, air temp, pressure) come from the nearest full met station.
    Water temp and water level come from the tide station itself.
    """
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = {
            ex.submit(fetch_obs, met_id,  "air_temperature"):   "air_temperature",
            ex.submit(fetch_obs, met_id,  "wind"):               "wind",
            ex.submit(fetch_obs, met_id,  "air_pressure"):       "air_pressure",
            ex.submit(fetch_obs, met_id,  "water_temperature"):  "water_temperature",
            ex.submit(fetch_water_level_obs, tide_id):           "water_level",
        }
        for fut, prod in futures.items():
            try:
                results[prod] = fut.result()
            except Exception:
                results[prod] = None
    return results


# ── Wind helpers ──────────────────────────────────────────────────────────────
def wind_dir_arrow(degrees: float) -> str:
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(degrees / 22.5) % 16]


def wind_color(mph: float) -> str:
    if mph < 10:  return BGREEN
    if mph < 15:  return BYELLOW
    if mph < 20:  return YELLOW
    if mph < 25:  return BRED
    return RED


def beaufort(mph: float) -> str:
    if mph < 1:   return "Calm"
    if mph < 4:   return "Light air"
    if mph < 8:   return "Light breeze"
    if mph < 13:  return "Gentle breeze"
    if mph < 19:  return "Moderate breeze"
    if mph < 25:  return "Fresh breeze"
    if mph < 32:  return "Strong breeze"
    return "Near gale+"


# ── Fishing rating ────────────────────────────────────────────────────────────
def fishing_rating(hilo_events: list, obs: dict, sol: dict) -> tuple:
    """Return (stars_str, label, color) fishing conditions summary."""
    now_h = datetime.now().hour + datetime.now().minute / 60
    score = 0

    # Tide: within 1.5 hours of any hi/lo event = +2
    for t, _, _ in hilo_events:
        diff = abs((t.hour + t.minute / 60) - now_h)
        if diff < 1.5:
            score += 2
            break
        if diff < 3:
            score += 1
            break

    # Wind: < 10 mph = +2, < 15 = +1
    try:
        wspd = float(obs.get("wind", {}).get("s", 99))
        if wspd < 10:  score += 2
        elif wspd < 15: score += 1
    except (TypeError, ValueError, AttributeError):
        pass

    # Solunar: during a major = +2, minor = +1
    for key in ("major1", "major2"):
        start = sol[key]
        dur = 2
        end = (start + dur) % 24
        in_period = (start <= now_h < end) if start < end else (now_h >= start or now_h < end)
        if in_period:
            score += 2
            break
    else:
        for key in ("minor1", "minor2"):
            start = sol[key]
            dur = 1
            end = (start + dur) % 24
            in_period = (start <= now_h < end) if start < end else (now_h >= start or now_h < end)
            if in_period:
                score += 1
                break

    if score >= 5:   return "★★★★★", "Excellent",  BGREEN
    if score >= 4:   return "★★★★☆", "Very Good",  BGREEN
    if score >= 3:   return "★★★☆☆", "Good",       BGREEN
    if score >= 2:   return "★★☆☆☆", "Fair",       BYELLOW
    return           "★☆☆☆☆", "Poor",       RED


# ── Rendering ─────────────────────────────────────────────────────────────────
def box_line(content: str, width: int = 74) -> str:
    """Pad content to fill a box line (no border chars, caller adds them)."""
    visible = content.replace(RESET,"").replace(BOLD,"").replace(DIM,"")
    for code in [BWHITE,BGREEN,BYELLOW,BRED,BCYAN,BBLUE,BMAGENTA,
                 WHITE,GREEN,YELLOW,RED,CYAN,BLUE,MAGENTA,BLACK,
                 BG_DARK_BLUE,BG_NAVY,BG_SEA,BG_WATER]:
        visible = visible.replace(code, "")
    pad = width - len(visible)
    return content + " " * max(0, pad)


def draw_conditions(name: str, obs: dict, nws, sol: dict,
                    sunrise: float, sunset: float, solar_noon: float,
                    phase_name: str, phase_pct: int, phase_emoji: str,
                    hilo_events: list, is_today: bool = True) -> None:
    W = 74  # total inner width
    stars, rating_label, r_color = fishing_rating(hilo_events, obs, sol)

    # Helper to extract obs value safely
    def ov(key, field="v", default="N/A"):
        try:
            val = obs.get(key, {})
            if val is None: return default
            return val.get(field, default)
        except AttributeError:
            return default

    # ── Conditions header ──────────────────────────────────────────────────────
    print(f"\n{BG_SEA}{BWHITE}{BOLD}  {'Conditions — ' + name:<{W-2}}  {RESET}")

    # ── Weather row ───────────────────────────────────────────────────────────
    air_t  = ov("air_temperature");   wtr_t  = ov("water_temperature")
    wspd   = ov("wind", "s");          wdir   = ov("wind", "d");  wgst = ov("wind", "g")
    pres   = ov("air_pressure")
    wlev   = ov("water_level")

    # Air / water temp
    try:
        at = float(air_t);  at_str = f"{at:.0f}°F"
        at_col = BRED if at > 95 else (BYELLOW if at > 85 else BWHITE)
    except (TypeError, ValueError):
        at_str = "N/A"; at_col = DIM

    try:
        wt = float(wtr_t); wt_str = f"{wt:.1f}°F"
        wt_col = BCYAN if wt < 70 else (BGREEN if wt < 80 else BYELLOW)
    except (TypeError, ValueError):
        wt_str = "N/A"; wt_col = DIM

    # Wind
    try:
        ws = float(wspd); wd = float(wdir); wg = float(wgst)
        dir_str  = wind_dir_arrow(wd)
        wnd_col  = wind_color(ws)
        wind_str = f"{wnd_col}{dir_str} {ws:.0f} mph{RESET}"
        if wg > ws + 3:
            wind_str += f" {DIM}(gusts {wg:.0f}){RESET}"
        wind_str += f"  {DIM}{beaufort(ws)}{RESET}"
    except (TypeError, ValueError):
        wind_str = f"{DIM}N/A{RESET}"

    # Pressure
    try:
        p = float(pres)
        pres_str = f"{p:.2f} mb"
    except (TypeError, ValueError):
        pres_str = "N/A"

    # Water level offset
    try:
        wl = float(wlev)
        sign = "+" if wl >= 0 else ""
        wl_col = BBLUE if abs(wl) < 0.5 else BYELLOW
        wl_str = f"{wl_col}{sign}{wl:.2f} ft MLLW{RESET}"
    except (TypeError, ValueError):
        wl_str = f"{DIM}N/A{RESET}"

    print(f"  {BOLD}Air{RESET}  {at_col}{at_str}{RESET}    "
          f"{BOLD}Water{RESET}  {wt_col}{wt_str}{RESET}    "
          f"{BOLD}Pressure{RESET}  {pres_str}    "
          f"{BOLD}Level{RESET}  {wl_str}")
    print(f"  {BOLD}Wind{RESET}  {wind_str}")

    # ── NWS conditions ────────────────────────────────────────────────────────
    if nws and nws.get("hourly"):
        cur = nws["hourly"][0]
        cond   = cur.get("shortForecast", "")
        temp   = cur.get("temperature", "")
        wpct   = cur.get("probabilityOfPrecipitation", {}).get("value") or 0
        wspd_s = cur.get("windSpeed", "")
        wdir_s = cur.get("windDirection", "")
        cond_col = BCYAN if "Sunny" in cond or "Clear" in cond else \
                   (BYELLOW if "Cloud" in cond else \
                   (BRED if "Storm" in cond or "Thunder" in cond else BWHITE))
        print(f"  {BOLD}NWS{RESET}   {cond_col}{cond}{RESET}  "
              f"{DIM}{temp}°F  Wind {wdir_s} {wspd_s}  Rain {wpct}%{RESET}")

        if nws.get("forecast"):
            fc = nws["forecast"]
            for period in fc[:2]:
                pname = period.get("name", "")
                pdetail = period.get("detailedForecast", "")[:80]
                print(f"  {DIM}  {pname}: {pdetail}{RESET}")

    print()

    # ── Sun / Moon row ────────────────────────────────────────────────────────
    print(f"  {BG_DARK_BLUE}{BWHITE}{BOLD}  Sun & Moon  {RESET}")

    if sunrise and sunset:
        golden_eve = sunset - 1
        print(f"  {BYELLOW}☀  Sunrise{RESET}  {hhmm(sunrise)}    "
              f"{BYELLOW}Solar Noon{RESET}  {hhmm(solar_noon)}    "
              f"{BYELLOW}Sunset{RESET}  {hhmm(sunset)}    "
              f"{DIM}Golden hr{RESET}  {hhmm(golden_eve)}–{hhmm(sunset)}")
    else:
        print(f"  {DIM}Sun times unavailable{RESET}")

    print(f"  {BWHITE}{phase_emoji}  {phase_name}{RESET}  {DIM}{phase_pct}% illuminated{RESET}")
    print()

    # ── Solunar periods ───────────────────────────────────────────────────────
    now_h = datetime.now().hour + datetime.now().minute / 60

    def in_period(start, dur):
        end = (start + dur) % 24
        return (start <= now_h < end) if start < end else (now_h >= start or now_h < end)

    def period_str(start, dur, label, col):
        end = (start + dur) % 24
        active = is_today and in_period(start, dur)
        marker = f"{BGREEN} ◀ NOW{RESET}" if active else ""
        return (f"  {col}{BOLD}{label}{RESET}  "
                f"{hhmm(start)} – {hhmm(end)}{marker}")

    print(f"  {BG_DARK_BLUE}{BWHITE}{BOLD}  Solunar Feeding Periods  {RESET}")
    print(period_str(sol["major1"], 2, "◉ MAJOR", BBLUE) +
          "    " + period_str(sol["major2"], 2, "◉ MAJOR", BBLUE).strip())
    print(period_str(sol["minor1"], 1, "○ minor", CYAN) +
          "    " + period_str(sol["minor2"], 1, "○ minor", CYAN).strip())
    print()

    # ── Fishing rating ────────────────────────────────────────────────────────
    if is_today:
        print(f"  {BOLD}Current Fishing Conditions:{RESET}  "
              f"{r_color}{BOLD}{stars}  {rating_label}{RESET}")
        print()


# ── Tide chart (existing, unchanged) ─────────────────────────────────────────
def tide_color(height: float, min_h: float, max_h: float) -> str:
    rng   = max_h - min_h if max_h != min_h else 1
    ratio = (height - min_h) / rng
    if ratio > 0.80:  return BBLUE
    if ratio > 0.60:  return BCYAN
    if ratio > 0.40:  return CYAN
    if ratio > 0.20:  return GREEN
    return YELLOW


def build_hourly_map(hourly: list) -> dict:
    hmap = {}
    for p in hourly:
        try:
            t = datetime.strptime(p["t"], "%Y-%m-%d %H:%M")
            hmap[t.hour] = float(p["v"])
        except (KeyError, ValueError):
            pass
    return hmap


def draw_chart(name: str, hourly: list, hilo: list, target_date: date = None) -> None:
    if target_date is None:
        target_date = date.today()
    is_today = (target_date == date.today())

    heights = [float(p["v"]) for p in hourly if "v" in p]
    if not heights:
        print(f"{RED}No data for {name}{RESET}"); return

    min_h = min(heights); max_h = max(heights)
    hmap  = build_hourly_map(hourly)

    hilo_events = []
    for p in hilo:
        try:
            t   = datetime.strptime(p["t"], "%Y-%m-%d %H:%M")
            hilo_events.append((t, float(p["v"]), p["type"]))
        except (KeyError, ValueError):
            pass

    # Header
    title     = f"  Tide Chart — {name}  "
    date_str  = target_date.strftime("%A, %B %d, %Y")
    pad       = (CHART_WIDTH - len(title)) // 2
    print()
    print(f"{BG_DARK_BLUE}{BWHITE}{BOLD}" + " " * pad + title
          + " " * (CHART_WIDTH - pad - len(title)) + RESET)
    print(f"{DIM}{WHITE}  {date_str}  (all times local • heights in feet MLLW){RESET}")
    print()

    # Chart body
    col_w = CHART_WIDTH // 24
    now_h = datetime.now().hour
    for row in range(CHART_HEIGHT, -1, -1):
        height_at_row = min_h + (max_h - min_h) * row / CHART_HEIGHT
        label = f"{height_at_row:4.1f}ft" if row % 4 == 0 else "       "
        line  = f"{DIM}{WHITE}{label}{RESET} {DIM}│{RESET}"
        for hour in range(24):
            h = hmap.get(hour)
            if h is None:
                prev_h = hmap.get(hour - 1); next_h = hmap.get(hour + 1)
                h = (prev_h + next_h) / 2 if prev_h and next_h else min_h
            bar_rows = round((h - min_h) / (max_h - min_h) * CHART_HEIGHT)
            color    = tide_color(h, min_h, max_h)
            now_mark = is_today and hour == now_h
            if row <= bar_rows:
                if row == bar_rows:
                    ch = "▄" * col_w
                    line += f"{color}{BOLD}{ch}{RESET}"
                else:
                    ch = "█" * col_w
                    line += f"{color}{ch}{RESET}"
            else:
                if now_mark and row == bar_rows + 1:
                    line += f"{BYELLOW}{'▾' * col_w}{RESET}"
                elif row > CHART_HEIGHT - 2:
                    line += f"{DIM}{BLUE}{'·' * col_w}{RESET}"
                else:
                    line += " " * col_w
        print(line)

    # X-axis
    print(f"       {DIM}└{'─' * CHART_WIDTH}{RESET}")
    hour_line = "        "
    for h in range(24):
        label = ("12a" if h == 0 else ("12p" if h == 12
                 else (f"{h}a" if h < 12 else f"{h-12}p")))
        hour_line += label[:col_w] + " " * max(0, col_w - len(label))
    print(f"{DIM}{WHITE}{hour_line}{RESET}")
    print(f"        {DIM}{'Hour (local time)':^{CHART_WIDTH}}{RESET}")
    print()

    # Hi/Lo table
    print(f"  {BOLD}{BWHITE}High / Low Tides:{RESET}")
    print(f"  {DIM}{'─' * 36}{RESET}")
    now_h_dec = datetime.now().hour + datetime.now().minute / 60
    for t, val, typ in hilo_events:
        event_h = t.hour + t.minute / 60
        diff    = event_h - now_h_dec
        if typ == "H":
            icon = f"{BBLUE}▲ HIGH{RESET}"; col = BCYAN
        else:
            icon = f"{BYELLOW}▼ LOW {RESET}"; col = YELLOW
        time_str = t.strftime("%I:%M %p")
        if -0.5 < diff < 0:
            when = f"{DIM}(just passed){RESET}"
        elif 0 <= diff < 6:
            h_away = int(diff); m_away = int((diff - h_away) * 60)
            when = f"{DIM}(in {h_away}h {m_away:02d}m){RESET}" if h_away else \
                   f"{DIM}(in {m_away}m){RESET}"
        else:
            when = ""
        print(f"  {icon}  {BWHITE}{time_str}{RESET}  {col}{val:+.2f} ft{RESET}  {when}")
    print()

    # Legend
    items = [(BBLUE,"Very High"),(BCYAN,"High"),(CYAN,"Mid-High"),
             (GREEN,"Mid-Low"),(YELLOW,"Low")]
    print(f"  {DIM}Legend:{RESET} ", end="")
    for col, lbl in items:
        print(f"{col}█{RESET} {DIM}{lbl}{RESET}  ", end="")
    print("\n")


# ── Weekly summary ───────────────────────────────────────────────────────────
def draw_week(name: str, hilo_all: list, start: date, end: date) -> None:
    """Display a compact 7-day hi/lo tide table."""
    by_date: dict = {}
    for p in hilo_all:
        try:
            t = datetime.strptime(p["t"], "%Y-%m-%d %H:%M")
            by_date.setdefault(t.date(), []).append((t, float(p["v"]), p["type"]))
        except (KeyError, ValueError):
            pass

    W = 76
    range_str = f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    title = f"  Tide Week — {name}  ({range_str})  "
    print()
    print(f"{BG_NAVY}{BWHITE}{BOLD}{title:^{W}}{RESET}")
    print()

    today = date.today()
    cur = start
    while cur <= end:
        phase_name, _, phase_emoji = moon_phase(cur)
        day_label = cur.strftime("%a %b %d")
        if cur == today:
            print(f"  {BGREEN}{BOLD}{day_label}  ◄ TODAY{RESET}  {phase_emoji} {DIM}{phase_name}{RESET}")
        else:
            print(f"  {BWHITE}{BOLD}{day_label}{RESET}  {phase_emoji} {DIM}{phase_name}{RESET}")

        events = sorted(by_date.get(cur, []), key=lambda x: x[0])
        if events:
            for t, val, typ in events:
                if typ == "H":
                    icon = f"{BBLUE}▲ HIGH{RESET}"; col = BCYAN
                else:
                    icon = f"{BYELLOW}▼ LOW {RESET}"; col = YELLOW
                print(f"    {icon}  {BWHITE}{t.strftime('%I:%M %p')}{RESET}  {col}{val:+.2f} ft{RESET}")
        else:
            print(f"    {DIM}No data{RESET}")
        print()
        cur += timedelta(days=1)


# ── Interactive prompts ───────────────────────────────────────────────────────
def prompt_date() -> date:
    """Interactively prompt for a date; Enter accepts today."""
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    print(f"\n{BG_DARK_BLUE}{BWHITE}{BOLD}  Date Selection  {RESET}")
    print(f"  {DIM}Press Enter for today ({today_str}), or type YYYY-MM-DD:{RESET}")
    try:
        raw = input(f"  {BYELLOW}Date: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return today
    if not raw:
        return today
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        print(f"  {RED}Invalid date — using today ({today_str}){RESET}")
        return today


def prompt_station() -> dict | None:
    """Interactively prompt for a station search; Enter uses Freeport TX default."""
    print(f"\n{BG_DARK_BLUE}{BWHITE}{BOLD}  Station Search  {RESET}")
    print(f"  {DIM}Search NOAA stations by city or name — press Enter for Freeport TX:{RESET}")
    try:
        query = input(f"  {BYELLOW}Search: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return None
    if not query:
        return None  # caller uses default
    return pick_station(query)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="ANSI tide chart — Texas Gulf Coast or any NOAA station")
    parser.add_argument("--padre", "-p", action="store_true",
                        help="also show North Padre Island, TX (default stations)")
    parser.add_argument("--search", "-s", metavar="QUERY",
                        help="search any of ~3,450 NOAA stations by city or name")
    parser.add_argument("--id", metavar="STATION_ID",
                        help="use a specific NOAA station ID directly")
    parser.add_argument("--date", "-d", metavar="YYYY-MM-DD",
                        help="date to show tide predictions (default: today)")
    parser.add_argument("--week", "-w", nargs="?", const="this",
                        metavar="this|next|last",
                        help="show full week of hi/lo tides (default: this week)")
    args = parser.parse_args()

    if args.week is not None and args.week not in ("this", "next", "last"):
        print(f"{RED}--week must be 'this', 'next', or 'last'{RESET}")
        sys.exit(1)

    # fully interactive when no flags at all
    interactive = (not args.id and not args.search and not args.padre
                   and not args.date and not args.week)

    # ── Resolve target date (single-day mode only) ─────────────────────────────
    if not args.week:
        if args.date:
            try:
                target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print(f"{RED}Invalid date '{args.date}' — use YYYY-MM-DD{RESET}")
                sys.exit(1)
        elif interactive:
            target_date = prompt_date()
        else:
            target_date = date.today()

        is_today  = (target_date == date.today())
        date_str  = target_date.strftime("%Y%m%d")
        utc_off   = central_utc_offset(target_date)

    # ── Resolve station(s) ─────────────────────────────────────────────────────
    if args.id:
        info = fetch_station_info(args.id)
        if not info:
            print(f"{RED}Station '{args.id}' not found — check the ID at "
                  f"tidesandcurrents.noaa.gov{RESET}")
            sys.exit(1)
        print(f"{BGREEN}  Using: {info['name']}  ({info['id']}){RESET}")
        selected = {info["name"]: {
            "id":     info["id"],
            "lat":    info["lat"],
            "lon":    info["lon"],
            "met_id": info["id"],
            "nws":    f"https://api.weather.gov/points/{info['lat']},{info['lon']}",
        }}
    elif args.search:
        station = pick_station(args.search)
        if not station:
            sys.exit(1)
        selected = {station["name"]: {
            "id":     station["id"],
            "lat":    station["lat"],
            "lon":    station["lon"],
            "met_id": station["id"],
            "nws":    f"https://api.weather.gov/points/{station['lat']},{station['lon']}",
        }}
    elif interactive:
        station = prompt_station()
        if station:
            selected = {station["name"]: {
                "id":     station["id"],
                "lat":    station["lat"],
                "lon":    station["lon"],
                "met_id": station["id"],
                "nws":    f"https://api.weather.gov/points/{station['lat']},{station['lon']}",
            }}
        else:
            selected = {"Freeport, TX": STATIONS["Freeport, TX"]}
    else:
        selected = {"Freeport, TX": STATIONS["Freeport, TX"]}
        if args.padre:
            selected["North Padre Island, TX"] = STATIONS["North Padre Island, TX"]

    # ── Week mode ──────────────────────────────────────────────────────────────
    if args.week is not None:
        which = args.week or "this"
        week_start, week_end = week_dates(which)
        begin_str = week_start.strftime("%Y%m%d")
        end_str   = week_end.strftime("%Y%m%d")

        for name, cfg in selected.items():
            sid = cfg["id"]
            print(f"\n{BCYAN}  Fetching {which}-week tides for {name} (station {sid})…{RESET}")
            hilo_all = fetch_predictions(sid, begin_str, "hilo", end_date=end_str)
            draw_week(name, hilo_all, week_start, week_end)

        print(f"{DIM}  Data: NOAA CO-OPS (tidesandcurrents.noaa.gov){RESET}\n")
        return

    # Header
    print(f"\n{BG_NAVY}{BWHITE}{BOLD}{'':^80}{RESET}")
    print(f"{BG_NAVY}{BWHITE}{BOLD}{'  NOAA Tide Predictions — Texas Gulf Coast  ':^80}{RESET}")
    print(f"{BG_NAVY}{BWHITE}{BOLD}{'':^80}{RESET}")

    # Moon (same for all stations; date-specific)
    phase_name, phase_pct, phase_emoji = moon_phase(target_date)

    for name, cfg in selected.items():
        sid = cfg["id"]; lat = cfg["lat"]; lon = cfg["lon"]

        print(f"\n{BCYAN}  Fetching data for {name} (station {sid})…{RESET}")

        # Parallel fetch: tides + observations + NWS
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            f_hourly = ex.submit(fetch_predictions, sid, date_str, "h")
            f_hilo   = ex.submit(fetch_predictions, sid, date_str, "hilo")
            f_obs    = ex.submit(fetch_all_obs, sid, cfg["met_id"])
            f_nws    = ex.submit(fetch_nws, cfg["nws"])

        hourly = f_hourly.result()
        hilo   = f_hilo.result()
        obs    = f_obs.result()
        nws    = f_nws.result()

        # Astronomy
        rise, sset, noon = sun_times(target_date, lat, lon, utc_off)
        sol = solunar_times(target_date, lon, utc_off)

        # Parse hilo for rating + countdown
        hilo_events = []
        for p in hilo:
            try:
                hilo_events.append((
                    datetime.strptime(p["t"], "%Y-%m-%d %H:%M"),
                    float(p["v"]), p["type"]
                ))
            except (KeyError, ValueError):
                pass

        draw_conditions(name, obs, nws, sol, rise, sset, noon,
                        phase_name, phase_pct, phase_emoji, hilo_events,
                        is_today=is_today)
        draw_chart(name, hourly, hilo, target_date=target_date)

    print(f"{DIM}  Data: NOAA CO-OPS (tidesandcurrents.noaa.gov) · NWS (weather.gov){RESET}\n")


if __name__ == "__main__":
    main()
