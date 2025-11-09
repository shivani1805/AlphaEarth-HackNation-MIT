# -- coding: utf-8 --
# points_to_hazard_csv.py — flood, hurricane, + wildfire risk (free, no API keys)
#
# Input JSON (file or stdin), either schema:
# {
#   "points": [
#     {"name": "Boston_MA", "lat": 42.3601, "lon": -71.0589},
#     {"name": "Springfield_MA", "lat": 42.1015, "lon": -72.5898}
#   ],
#   "start_date": "2023-07-01T00:00:00Z",
#   "end_date":   "2023-07-20T00:00:00Z",
#   "timezone":   "America/New_York"
# }
# -- OR your earlier counties schema --
# {
#   "counties": [
#     {"county_name":"Barnstable","centroid_coordinates":{"latitude":41.72,"longitude":-70.24}}
#   ],
#   "start_date":"...", "end_date":"...", "timezone":"..."
# }
#
# Output CSV: results/csv/point_daily_metrics.csv
# Columns include:
#   date,name,lat,lon,
#   precip_mm,wind_kmh,wind_ms,gust_kmh,gust_ms,temp_max_c,rh_min_pct,
#   precip_3day,gust_3day_ms,
#   flood_score,hurricane_score,flood_category,hurricane_category,
#   precip7_mm,ffwi,ffwi_scaled,vpd_kpa,vpd_scaled,wildfire_score,wildfire_category
#
# Deps: requests, pandas, numpy  (tzdata optional on Windows)

import sys, os, json, time, requests
import pandas as pd
import numpy as np
from datetime import datetime

OUT_DIR  = os.path.join("results", "csv")
OUT_PATH = os.path.join(OUT_DIR, "point_daily_metrics.csv")

# ------------------ basic helpers ------------------
def read_payload():
    if not sys.stdin.isatty() and len(sys.argv) == 1:
        return json.loads(sys.stdin.read())
    elif len(sys.argv) >= 2:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise SystemExit("Provide payload JSON via file path or stdin.")

def iso_to_date(s):
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).date().isoformat()
    except Exception:
        return s[:10]

def extract_points(payload):
    pts = []
    if "points" in payload:
        for p in payload["points"]:
            pts.append((str(p["name"]), float(p["lat"]), float(p["lon"])))
    elif "counties" in payload:
        for c in payload["counties"]:
            name = str(c.get("county_name") or c.get("name"))
            lat  = float(c["centroid_coordinates"]["latitude"])
            lon  = float(c["centroid_coordinates"]["longitude"])
            pts.append((name, lat, lon))
    return pts

# ------------------ data fetch ------------------
def open_meteo_daily(lat, lon, start_date, end_date, tz):
    """
    Pull daily meteorology from Open-Meteo archive:
    - precip (mm), windspeed_10m_max (km/h), windgusts_10m_max (km/h),
      temperature_2m_max (°C), relative_humidity_2m_min (%)
    Convert wind to m/s for physics-based thresholds.
    """
    base = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "daily": ",".join([
            "precipitation_sum",
            "windspeed_10m_max",
            "windgusts_10m_max",
            "temperature_2m_max",
            "relative_humidity_2m_min"
        ]),
        "timezone": tz
    }
    r = requests.get(base, params=params, timeout=60)
    r.raise_for_status()
    j = r.json()
    daily = j.get("daily", {})
    dates = daily.get("time", [])
    if not dates:
        return pd.DataFrame(columns=[
            "date","precip_mm","wind_kmh","wind_ms","gust_kmh","gust_ms","temp_max_c","rh_min_pct"
        ])
    df = pd.DataFrame({
        "date":        pd.to_datetime(dates),
        "precip_mm":   pd.to_numeric(daily.get("precipitation_sum", []), errors="coerce"),
        "wind_kmh":    pd.to_numeric(daily.get("windspeed_10m_max", []), errors="coerce"),
        "gust_kmh":    pd.to_numeric(daily.get("windgusts_10m_max", []), errors="coerce"),
        "temp_max_c":  pd.to_numeric(daily.get("temperature_2m_max", []), errors="coerce"),
        "rh_min_pct":  pd.to_numeric(daily.get("relative_humidity_2m_min", []), errors="coerce"),
    })
    # Convert km/h -> m/s
    df["wind_ms"] = df["wind_kmh"] * 0.2777777778
    df["gust_ms"] = df["gust_kmh"] * 0.2777777778
    return df

# ------------------ scoring helpers ------------------
def logistic_from_z(z, alpha=1.8, beta=0.0):
    """z -> 0..100 logistic; beta=0 keeps average ~50."""
    return 100.0 / (1.0 + np.exp(-alpha * (z - beta)))

def score_series(x):
    arr = x.astype(float).to_numpy()
    mu  = np.nanmean(arr)
    sd  = np.nanstd(arr) + 1e-9
    z   = (arr - mu) / sd
    return pd.Series(logistic_from_z(z), index=x.index)

# Flood categories from 3-day precip
def flood_category_from_raw(precip_3day_mm):
    if pd.isna(precip_3day_mm): return None
    if precip_3day_mm < 25: return "Low"
    if precip_3day_mm < 75: return "Medium"
    return "High"

# Hurricane categories from DAILY gust (m/s)
def hurricane_category_from_raw(gust_ms):
    if pd.isna(gust_ms): return None
    if gust_ms < 17: return "Low"          # ~<34 kt
    if gust_ms < 33: return "Medium"       # ~34–63 kt
    return "High"                           # ~>=64 kt

# --- Wildfire components ---
def dryness_score_from_precip7(precip7_mm):
    # Monotonic: <=5mm -> 100 (very dry), >=20mm -> 0 (wet), linear in between
    if pd.isna(precip7_mm): return None
    if precip7_mm <= 5:  return 100.0
    if precip7_mm >= 20: return 0.0
    # linear from 5mm(100) to 20mm(0)
    return float((20 - precip7_mm) * (100.0 / 15.0))

def vpd_kpa_from_t_rh(t_c, rh_min_pct):
    # Tetens formula
    if pd.isna(t_c) or pd.isna(rh_min_pct): return None
    es = 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))  # kPa
    ea = es * (rh_min_pct / 100.0)
    vpd = max(0.0, es - ea)
    return float(vpd)

def scale_vpd_to_100(vpd_kpa):
    if vpd_kpa is None or pd.isna(vpd_kpa): return None
    return float(min(100.0, 100.0 * vpd_kpa / 4.0))  # clip at 4 kPa

def ffwi_from_t_rh_wind(t_c, rh_min_pct, wind_ms):
    # Simplified Fosberg Fire Weather Index (approx.)
    # Convert for formula
    if pd.isna(t_c) or pd.isna(rh_min_pct) or pd.isna(wind_ms):
        return None
    T_F = t_c * 9.0/5.0 + 32.0
    U_mph = max(0.0, float(wind_ms) * 2.236936)  # m/s -> mph
    U_mph = min(U_mph, 30.0)  # stabilize
    RH = float(max(0.0, min(100.0, rh_min_pct)))

    # Fine fuel moisture (approx formula)
    m = (0.03229 + 0.281073*RH + 0.000578*RH*RH
         + 1e-7*RH*3 - 0.0000035*(RH**2)*T_F)
    m = float(max(1.0, min(30.0, m)))

    # Damping & wind term
    eta = 1.0 - 2.0*(m/30.0) + (m/30.0)**2
    eta = max(0.0, min(1.0, eta))
    fU  = np.sqrt(1.0 + U_mph*U_mph)

    ffwi = 10.0 * eta * fU
    return float(max(0.0, min(ffwi, 60.0)))  # clip at 60

def scale_ffwi_to_100(ffwi):
    if ffwi is None or pd.isna(ffwi): return None
    return float(min(100.0, 100.0 * ffwi / 60.0))

def wildfire_category(score):
    if score is None or pd.isna(score): return None
    if score < 35: return "Low"
    if score < 65: return "Medium"
    return "High"

# ------------------ main ------------------
def main():
    payload = read_payload()
    tz = payload.get("timezone", "UTC")
    try:
        start_date = iso_to_date(payload["start_date"])
        end_date   = iso_to_date(payload["end_date"])
    except KeyError as e:
        raise SystemExit(f"Missing key in payload: {e}. Required: start_date, end_date")

    pts_rows = extract_points(payload)
    if not pts_rows:
        raise SystemExit("Payload must include 'points' or 'counties' with valid coordinates.")

    os.makedirs(OUT_DIR, exist_ok=True)

    rows = []
    for name, lat, lon in pts_rows:
        try:
            d = open_meteo_daily(lat, lon, start_date, end_date, tz)
            if d.empty:
                continue
            d = d.sort_values("date").reset_index(drop=True)
            d["name"] = name; d["lat"] = lat; d["lon"] = lon
            rows.append(d)
        except Exception as e:
            print(f"warn: failed {name} ({lat},{lon}) -> {e}")
        time.sleep(0.05)

    if not rows:
        raise SystemExit("No data returned from Open-Meteo for the given dates/points.")

    df = pd.concat(rows, ignore_index=True).sort_values(["name","date"]).reset_index(drop=True)

    def add_rolls(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        g["precip_3day"]    = g["precip_mm"].rolling(3, min_periods=1).sum()
        g["gust_3day_ms"]   = g["gust_ms"].rolling(3, min_periods=1).max()
        g["precip7_mm"]     = g["precip_mm"].rolling(7, min_periods=1).sum()
        return g
    df = df.groupby("name", group_keys=False).apply(add_rolls)

    def add_flood_hurr_scores(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        g["flood_score"]     = score_series(g["precip_3day"])
        g["hurricane_score"] = score_series(g["gust_3day_ms"])
        g["flood_category"]     = g["precip_3day"].apply(flood_category_from_raw)
        g["hurricane_category"] = g["gust_ms"].apply(hurricane_category_from_raw)
        return g
    df = df.groupby("name", group_keys=False).apply(add_flood_hurr_scores)


    def add_wildfire(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        g["dryness_score"] = g["precip7_mm"].apply(dryness_score_from_precip7)
        g["vpd_kpa"]       = [vpd_kpa_from_t_rh(t, rh) for t, rh in zip(g["temp_max_c"], g["rh_min_pct"])]
        g["vpd_scaled"]    = g["vpd_kpa"].apply(scale_vpd_to_100)
        g["ffwi"]          = [ffwi_from_t_rh_wind(t, rh, w) for t, rh, w in zip(g["temp_max_c"], g["rh_min_pct"], g["wind_ms"])]
        g["ffwi_scaled"]   = g["ffwi"].apply(scale_ffwi_to_100)
        def combine(dry, ff, vpd):
            if dry is None or pd.isna(dry): return None
            if ff  is None or pd.isna(ff):  return None
            if vpd is None or pd.isna(vpd): return None
            return 0.40*float(dry) + 0.35*float(ff) + 0.25*float(vpd)
        g["wildfire_score"]     = [combine(d, f, v) for d, f, v in zip(g["dryness_score"], g["ffwi_scaled"], g["vpd_scaled"])]
        g["wildfire_category"]  = g["wildfire_score"].apply(wildfire_category)
        return g
    df = df.groupby("name", group_keys=False).apply(add_wildfire)

    cols = ["date","name","lat","lon",
            "precip_mm","wind_kmh","wind_ms","gust_kmh","gust_ms","temp_max_c","rh_min_pct",
            "precip_3day","gust_3day_ms",
            "flood_score","hurricane_score","flood_category","hurricane_category",
            "precip7_mm","ffwi","ffwi_scaled","vpd_kpa","vpd_scaled","wildfire_score","wildfire_category"]
    df = df[cols]
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Saved: {OUT_PATH}")
    try:
        print(df.head(12).to_string(index=False))
    except Exception:
        pass

if __name__ == "__main__":
    main()