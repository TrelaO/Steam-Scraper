import ast
import datetime
import numpy as np
import pandas as pd


def safe_app_id(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return None
    if val is None or pd.isna(val):
        return None
    try:
        if isinstance(val, (int, np.integer)):
            return str(val)
        if isinstance(val, (float, np.floating)):
            if np.isnan(val):
                return None
            return str(int(val))
        val_str = str(val).strip()
        if val_str.endswith(".0"):
            val_str = val_str[:-2]
        return val_str if val_str else None
    except Exception:
        return None


def safe_str(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return None
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


def safe_int(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return None
    if val is None or pd.isna(val):
        return None
    try:
        return int(float(val))
    except Exception:
        return None


def safe_float(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return None
    if val is None or pd.isna(val):
        return None
    try:
        f = float(val)
        return f if not np.isnan(f) else None
    except Exception:
        return None


def safe_bool(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return False
    if val is None or pd.isna(val):
        return False
    if isinstance(val, (bool, np.bool_)):
        return bool(val)
    s = str(val).strip().lower()
    return s in ("true", "1", "t", "yes")


def safe_date(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return None
    if val is None or pd.isna(val):
        return None
    try:
        dt = pd.to_datetime(val, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def parse_owners(val):
    if isinstance(val, (list, tuple, np.ndarray, dict)):
        return None, None
    if val is None or pd.isna(val):
        return None, None
    val_str = str(val).strip()
    if "-" in val_str:
        parts = val_str.split("-")
        try:
            o_min = int(parts[0].strip().replace(",", ""))
            o_max = int(parts[1].strip().replace(",", ""))
            return o_min, o_max
        except Exception:
            pass
    return None, None


def extract_genres(val):
    if isinstance(val, (list, tuple, np.ndarray)):
        res = []
        for item in val:
            if isinstance(item, str):
                res.append(item.strip())
            elif isinstance(item, dict):
                if "description" in item:
                    res.append(str(item["description"]).strip())
                elif "name" in item:
                    res.append(str(item["name"]).strip())
        return [g for g in res if g]
    if isinstance(val, dict):
        return [str(k).strip() for k in val.keys() if k]
    if val is None or pd.isna(val):
        return []
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("[]", "nan", "none", "null"):
        return []
    if val_str.startswith("[") and val_str.endswith("]"):
        try:
            parsed = ast.literal_eval(val_str)
            if isinstance(parsed, list):
                return extract_genres(parsed)
        except Exception:
            pass
    return [g.strip() for g in val_str.split(",") if g.strip()]


def run_etl(df, conn):
    cur = conn.cursor()

    today_dt = datetime.date.today()
    today_iso = today_dt.isoformat()
    today_int = int(today_dt.strftime("%Y%m%d"))

    cur.execute("SELECT date_sk, full_date FROM dim_date")
    date_rows = cur.fetchall()
    date_sk = None
    for sk, fdate in date_rows:
        if str(fdate) == today_iso or sk == today_int:
            date_sk = sk
            break
    if date_sk is None and date_rows:
        date_sk = date_rows[-1][0]

    cur.execute(
        "SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform"
    )
    plat_rows = cur.fetchall()
    plat_map = {}
    for p_sk, w, m, l in plat_rows:
        plat_map[(bool(w), bool(m), bool(l))] = p_sk

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0,
    }

    records = df.to_dict("records")
    for row in records:
        app_id = safe_app_id(row.get("app_id"))
        if app_id is None:
            continue

        game_name = safe_str(row.get("name"))
        required_age = safe_int(row.get("required_age"))
        release_date = safe_date(row.get("release_date"))
        estimated_owners = safe_str(row.get("estimated_owners"))
        owners_min, owners_max = parse_owners(row.get("estimated_owners"))

        cur.execute(
            """
            INSERT OR IGNORE INTO dim_game 
            (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                app_id,
                game_name,
                required_age,
                release_date,
                estimated_owners,
                owners_min,
                owners_max,
            ),
        )
        if cur.rowcount > 0:
            counts["dim_game"] += 1

        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        game_sk_row = cur.fetchone()
        if not game_sk_row:
            continue
        game_sk = game_sk_row[0]

        genres = extract_genres(row.get("genres"))
        for g_name in genres:
            cur.execute(
                "INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)",
                (g_name,),
            )
            if cur.rowcount > 0:
                counts["dim_genre"] += 1

            cur.execute(
                "SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (g_name,)
            )
            g_row = cur.fetchone()
            if g_row:
                genre_sk = g_row[0]
                cur.execute(
                    "INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)",
                    (game_sk, genre_sk),
                )
                if cur.rowcount > 0:
                    counts["bridge_game_genre"] += 1

        win_flag = safe_bool(row.get("windows"))
        mac_flag = safe_bool(row.get("mac"))
        lin_flag = safe_bool(row.get("linux"))
        platform_sk = plat_map.get((win_flag, mac_flag, lin_flag))

        price_usd = safe_float(row.get("price"))
        discount_pct = safe_int(row.get("discount"))
        peak_ccu = safe_int(row.get("peak_ccu"))
        positive_reviews = safe_int(row.get("positive"))
        negative_reviews = safe_int(row.get("negative"))
        avg_playtime = safe_int(row.get("average_playtime_forever"))

        cur.execute(
            """
            INSERT INTO fact_game 
            (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_sk,
                date_sk,
                platform_sk,
                price_usd,
                discount_pct,
                peak_ccu,
                positive_reviews,
                negative_reviews,
                avg_playtime,
            ),
        )
        counts["fact_game"] += 1

    return counts