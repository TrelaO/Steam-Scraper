import ast
import datetime
import json
import numpy as np
import pandas as pd


def run_etl(df, conn):
    cursor = conn.cursor()

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0,
    }

    def safe_isna(val):
        if val is None:
            return True
        if isinstance(val, (dict, list, tuple)):
            return False
        try:
            return bool(pd.isna(val))
        except Exception:
            return False

    def parse_val(v):
        if safe_isna(v):
            return None
        if isinstance(v, (dict, list)):
            return v
        if isinstance(v, str):
            v_str = v.strip()
            if (v_str.startswith("{") and v_str.endswith("}")) or (
                v_str.startswith("[") and v_str.endswith("]")
            ):
                try:
                    return ast.literal_eval(v_str)
                except Exception:
                    try:
                        return json.loads(v_str.replace("'", '"'))
                    except Exception:
                        return v_str
            return v_str
        return v

    def safe_int(val, default=None):
        if safe_isna(val):
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def safe_float(val, default=0.0):
        if safe_isna(val):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # Date lookup
    today = datetime.date.today()
    today_iso = today.isoformat()
    today_int = int(today.strftime("%Y%m%d"))

    cursor.execute(
        "SELECT date_sk FROM dim_date WHERE full_date = ? OR date_sk = ?",
        (today_iso, today_int),
    )
    row = cursor.fetchone()
    if row:
        date_sk = row[0]
    else:
        cursor.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        row = cursor.fetchone()
        date_sk = row[0] if row else today_int

    # Platform lookup map
    cursor.execute(
        "SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform"
    )
    platform_rows = cursor.fetchall()
    platform_map = {}
    for psk, w, m, l in platform_rows:
        platform_map[(bool(w), bool(m), bool(l))] = psk

    # Standardize input records
    col_names = [str(c) for c in df.columns]
    has_std_cols = any(
        c.lower() in ["app_id", "appid", "game_name", "name", "title"]
        for c in col_names
    )

    games = []
    if not has_std_cols and len(df.columns) > 0:
        for col in df.columns:
            s = df[col]
            app_id_str = str(col).replace(".0", "").strip()
            rec = {"app_id": app_id_str}

            for idx, val in s.items():
                rec[str(idx).lower().strip()] = val

            vals = list(s)
            if "name" not in rec and "game_name" not in rec and len(vals) > 0:
                rec["name"] = vals[0]
            if "release_date" not in rec and len(vals) > 1:
                rec["release_date"] = vals[1]
            if "required_age" not in rec and len(vals) > 2:
                rec["required_age"] = vals[2]
            if "price" not in rec and len(vals) > 3:
                rec["price"] = vals[3]
            if "owners" not in rec and len(vals) > 4:
                rec["owners"] = vals[4]
            if "platforms" not in rec and len(vals) > 5:
                rec["platforms"] = vals[5]
            if "metrics" not in rec and len(vals) > 6:
                rec["metrics"] = vals[6]
            if "genres" not in rec and len(vals) > 7:
                rec["genres"] = vals[7]

            games.append(rec)
    else:
        for idx, row in df.iterrows():
            rec = row.to_dict()
            if "app_id" not in rec and "appid" not in rec and "id" not in rec:
                rec["app_id"] = str(idx)
            games.append(rec)

    for record in games:
        app_id_val = record.get("app_id") or record.get("appid") or record.get("id")
        if safe_isna(app_id_val):
            continue
        app_id = str(app_id_val).replace(".0", "").strip()
        if not app_id:
            continue

        game_name = (
            record.get("game_name")
            or record.get("name")
            or record.get("title")
        )
        game_name = (
            str(game_name).strip() if not safe_isna(game_name) else None
        )

        required_age = safe_int(
            record.get("required_age") or record.get("age"), 0
        )
        release_date = record.get("release_date") or record.get("date")
        release_date = (
            str(release_date).strip() if not safe_isna(release_date) else None
        )

        # Price parsing
        price_val = parse_val(
            record.get("price")
            or record.get("pricing")
            or record.get("price_usd")
        )
        if isinstance(price_val, dict):
            price_usd = safe_float(
                price_val.get(
                    "base_price_usd",
                    price_val.get("price_usd", price_val.get("price")),
                )
            )
            discount_pct = safe_int(
                price_val.get(
                    "current_discount_pct",
                    price_val.get("discount_pct", price_val.get("discount", 0)),
                ),
                0,
            )
        else:
            price_usd = safe_float(
                record.get("price_usd", record.get("price"))
            )
            discount_pct = safe_int(
                record.get("discount_pct", record.get("discount")), 0
            )

        # Owners parsing
        owners_val = parse_val(
            record.get("owners") or record.get("estimated_owners")
        )
        if isinstance(owners_val, dict):
            owners_min = safe_int(
                owners_val.get("min", owners_val.get("owners_min"))
            )
            owners_max = safe_int(
                owners_val.get("max", owners_val.get("owners_max"))
            )
            if owners_min is not None and owners_max is not None:
                estimated_owners = f"{owners_min} - {owners_max}"
            else:
                estimated_owners = str(owners_val)
        else:
            estimated_owners = (
                str(owners_val) if not safe_isna(owners_val) else None
            )
            owners_min = safe_int(record.get("owners_min"))
            owners_max = safe_int(record.get("owners_max"))

        # Platform parsing
        plat_val = parse_val(record.get("platforms") or record.get("platform"))
        if isinstance(plat_val, dict):
            win = bool(plat_val.get("windows", False))
            mac = bool(plat_val.get("mac", False))
            linux = bool(plat_val.get("linux", False))
        else:
            win = bool(
                record.get("supports_windows", record.get("windows", True))
            )
            mac = bool(record.get("supports_mac", record.get("mac", False)))
            linux = bool(
                record.get("supports_linux", record.get("linux", False))
            )

        # Metrics parsing
        metrics_val = parse_val(
            record.get("metrics")
            or record.get("engagement")
            or record.get("stats")
        )
        if isinstance(metrics_val, dict):
            peak_ccu = safe_int(
                metrics_val.get(
                    "peak_concurrent_users", metrics_val.get("peak_ccu", 0)
                ),
                0,
            )
            pos_rev = safe_int(
                metrics_val.get(
                    "reviews_positive", metrics_val.get("positive_reviews", 0)
                ),
                0,
            )
            neg_rev = safe_int(
                metrics_val.get(
                    "reviews_negative", metrics_val.get("negative_reviews", 0)
                ),
                0,
            )
            playtime = safe_int(
                metrics_val.get(
                    "avg_playtime_minutes",
                    metrics_val.get("average_playtime_mins", 0),
                ),
                0,
            )
        else:
            peak_ccu = safe_int(
                record.get("peak_ccu", record.get("peak_concurrent_users")), 0
            )
            pos_rev = safe_int(
                record.get("positive_reviews", record.get("reviews_positive")),
                0,
            )
            neg_rev = safe_int(
                record.get("negative_reviews", record.get("reviews_negative")),
                0,
            )
            playtime = safe_int(
                record.get(
                    "average_playtime_mins", record.get("avg_playtime_minutes")
                ),
                0,
            )

        # Genres parsing
        genres_val = parse_val(record.get("genres") or record.get("genre"))
        if isinstance(genres_val, list):
            genres_list = [
                str(g).strip() for g in genres_val if g and str(g).strip()
            ]
        elif isinstance(genres_val, str):
            genres_list = [
                g.strip()
                for g in genres_val.replace("[", "")
                .replace("]", "")
                .replace("'", "")
                .replace('"', "")
                .split(",")
                if g.strip()
            ]
        else:
            genres_list = []

        # Insert / Update dim_game
        cursor.execute(
            """
            INSERT INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(app_id) DO UPDATE SET
                game_name=excluded.game_name,
                required_age=excluded.required_age,
                release_date=excluded.release_date,
                estimated_owners=excluded.estimated_owners,
                owners_min=excluded.owners_min,
                owners_max=excluded.owners_max
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
        counts["dim_game"] += 1

        cursor.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        game_sk = cursor.fetchone()[0]

        # Insert genres and bridge
        for genre in genres_list:
            cursor.execute(
                "INSERT INTO dim_genre (genre_name) VALUES (?) ON CONFLICT(genre_name) DO NOTHING",
                (genre,),
            )
            if cursor.rowcount > 0:
                counts["dim_genre"] += cursor.rowcount

            cursor.execute(
                "SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (genre,)
            )
            genre_sk = cursor.fetchone()[0]

            cursor.execute(
                "INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)",
                (game_sk, genre_sk),
            )
            if cursor.rowcount > 0:
                counts["bridge_game_genre"] += cursor.rowcount

        # Lookup platform_sk
        platform_sk = platform_map.get((win, mac, linux))
        if platform_sk is None and platform_map:
            platform_sk = list(platform_map.values())[0]

        # Insert fact_game
        cursor.execute(
            """
            INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                game_sk,
                date_sk,
                platform_sk,
                price_usd,
                discount_pct,
                peak_ccu,
                pos_rev,
                neg_rev,
                playtime,
            ),
        )
        counts["fact_game"] += 1

    return counts