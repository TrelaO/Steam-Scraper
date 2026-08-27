import ast
import json
from datetime import datetime
import numpy as np
import pandas as pd


def safe_dict(val):
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, (list, tuple, np.ndarray)):
        return {}
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return {}
        try:
            res = json.loads(val)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        try:
            res = ast.literal_eval(val)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        return {}
    if pd.isna(val):
        return {}
    return {}


def safe_list(val):
    if val is None:
        return []
    if isinstance(val, (list, tuple, np.ndarray)):
        return list(val)
    if isinstance(val, dict):
        return []
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return []
        try:
            res = json.loads(val)
            if isinstance(res, list):
                return res
        except Exception:
            pass
        try:
            res = ast.literal_eval(val)
            if isinstance(res, list):
                return res
        except Exception:
            pass
        if "," in val:
            return [x.strip() for x in val.split(",") if x.strip()]
        return [val]
    if pd.isna(val):
        return []
    return []


def run_etl(df, conn):
    inserted_counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0,
    }

    cur = conn.cursor()

    today_str = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = ?", (today_str,))
    row_date = cur.fetchone()
    if row_date:
        date_sk = row_date[0]
    else:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        row_date = cur.fetchone()
        date_sk = row_date[0] if row_date else None

    cur.execute(
        "SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform"
    )
    platform_map = {}
    for p_sk, w, m, l in cur.fetchall():
        platform_map[(bool(w), bool(m), bool(l))] = p_sk

    records = df.to_dict("records")

    for row in records:
        app_id_raw = row.get("app_id")
        if app_id_raw is None:
            continue
        if isinstance(app_id_raw, (list, tuple, np.ndarray, dict)):
            continue
        if pd.isna(app_id_raw):
            continue

        app_id_str = str(app_id_raw).strip()
        if not app_id_str or app_id_str.lower() in ("nan", "none", "null"):
            continue

        g_name_val = row.get("title")
        if g_name_val is None:
            g_name_val = row.get("game_name")
        game_name = None
        if g_name_val is not None and not isinstance(
            g_name_val, (list, tuple, np.ndarray, dict)
        ):
            if not pd.isna(g_name_val):
                game_name = str(g_name_val).strip()

        req_age = row.get("age_rating")
        if req_age is None:
            req_age = row.get("required_age")
        required_age = None
        if req_age is not None and not isinstance(
            req_age, (list, tuple, np.ndarray, dict)
        ):
            if not pd.isna(req_age):
                try:
                    required_age = int(float(req_age))
                except Exception:
                    pass

        rel_date = row.get("release")
        if rel_date is None:
            rel_date = row.get("release_date")
        release_date = None
        if rel_date is not None and not isinstance(
            rel_date, (list, tuple, np.ndarray, dict)
        ):
            if not pd.isna(rel_date):
                release_date = str(rel_date).strip()

        owners_val = row.get("owners_estimate")
        if owners_val is None:
            owners_val = row.get("estimated_owners")
        owners_dict = safe_dict(owners_val)
        owners_min = None
        owners_max = None
        estimated_owners = None

        if owners_dict:
            min_v = owners_dict.get("min")
            max_v = owners_dict.get("max")
            if min_v is not None and not isinstance(
                min_v, (list, tuple, np.ndarray, dict)
            ):
                try:
                    owners_min = int(float(min_v))
                except Exception:
                    pass
            if max_v is not None and not isinstance(
                max_v, (list, tuple, np.ndarray, dict)
            ):
                try:
                    owners_max = int(float(max_v))
                except Exception:
                    pass
            if owners_min is not None and owners_max is not None:
                estimated_owners = f"{owners_min} - {owners_max}"
        elif owners_val is not None and not isinstance(
            owners_val, (list, tuple, np.ndarray, dict)
        ):
            if not pd.isna(owners_val):
                estimated_owners = str(owners_val).strip()

        cur.execute(
            "INSERT OR IGNORE INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                app_id_str,
                game_name,
                required_age,
                release_date,
                estimated_owners,
                owners_min,
                owners_max,
            ),
        )
        if cur.rowcount > 0:
            inserted_counts["dim_game"] += 1

        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id_str,))
        game_sk_row = cur.fetchone()
        if not game_sk_row:
            continue
        game_sk = game_sk_row[0]

        plat_dict = safe_dict(row.get("platforms"))
        win = bool(plat_dict.get("windows", False))
        mac = bool(plat_dict.get("mac", False))
        lin = bool(plat_dict.get("linux", False))
        platform_sk = platform_map.get((win, mac, lin))
        if platform_sk is None and platform_map:
            platform_sk = list(platform_map.values())[0]

        genres_list = safe_list(row.get("genres"))
        for g in genres_list:
            if g is None:
                continue
            if isinstance(g, (list, tuple, np.ndarray, dict)):
                continue
            if pd.isna(g):
                continue
            g_name = str(g).strip()
            if not g_name:
                continue

            cur.execute(
                "INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)",
                (g_name,),
            )
            if cur.rowcount > 0:
                inserted_counts["dim_genre"] += 1

            cur.execute(
                "SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (g_name,)
            )
            g_sk_row = cur.fetchone()
            if g_sk_row:
                genre_sk = g_sk_row[0]
                cur.execute(
                    "INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)",
                    (game_sk, genre_sk),
                )
                if cur.rowcount > 0:
                    inserted_counts["bridge_game_genre"] += 1

        pricing_d = safe_dict(row.get("pricing"))
        price_usd = pricing_d.get("base_price_usd")
        if price_usd is not None and not isinstance(
            price_usd, (list, tuple, np.ndarray, dict)
        ):
            try:
                price_usd = float(price_usd)
            except Exception:
                price_usd = None
        else:
            price_usd = None

        discount_pct = pricing_d.get("current_discount_pct")
        if discount_pct is not None and not isinstance(
            discount_pct, (list, tuple, np.ndarray, dict)
        ):
            try:
                discount_pct = int(float(discount_pct))
            except Exception:
                discount_pct = None
        else:
            discount_pct = None

        stats_d = safe_dict(row.get("stats"))
        peak_ccu = stats_d.get("peak_concurrent_users")
        if peak_ccu is None:
            peak_ccu = stats_d.get("peak_ccu")
        if peak_ccu is not None and not isinstance(
            peak_ccu, (list, tuple, np.ndarray, dict)
        ):
            try:
                peak_ccu = int(float(peak_ccu))
            except Exception:
                peak_ccu = None
        else:
            peak_ccu = None

        positive_reviews = stats_d.get("reviews_positive")
        if positive_reviews is None:
            positive_reviews = stats_d.get("positive_reviews")
        if positive_reviews is not None and not isinstance(
            positive_reviews, (list, tuple, np.ndarray, dict)
        ):
            try:
                positive_reviews = int(float(positive_reviews))
            except Exception:
                positive_reviews = None
        else:
            positive_reviews = None

        negative_reviews = stats_d.get("reviews_negative")
        if negative_reviews is None:
            negative_reviews = stats_d.get("negative_reviews")
        if negative_reviews is not None and not isinstance(
            negative_reviews, (list, tuple, np.ndarray, dict)
        ):
            try:
                negative_reviews = int(float(negative_reviews))
            except Exception:
                negative_reviews = None
        else:
            negative_reviews = None

        avg_playtime = stats_d.get("avg_playtime_mins")
        if avg_playtime is None:
            avg_playtime = stats_d.get("average_playtime_mins")
        if avg_playtime is None:
            avg_playtime = stats_d.get("avg_playtime")
        if avg_playtime is not None and not isinstance(
            avg_playtime, (list, tuple, np.ndarray, dict)
        ):
            try:
                avg_playtime = int(float(avg_playtime))
            except Exception:
                avg_playtime = None
        else:
            avg_playtime = None

        cur.execute(
            "INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        if cur.rowcount > 0:
            inserted_counts["fact_game"] += 1

    return inserted_counts