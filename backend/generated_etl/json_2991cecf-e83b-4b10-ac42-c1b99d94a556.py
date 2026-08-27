import pandas as pd
import numpy as np
import datetime
import ast

def run_etl(df, conn):
    cursor = conn.cursor()

    today_str = datetime.date.today().isoformat()
    today_int = int(datetime.date.today().strftime("%Y%m%d"))
    cursor.execute("SELECT date_sk FROM dim_date WHERE full_date = ?", (today_str,))
    d_row = cursor.fetchone()
    if not d_row:
        cursor.execute("SELECT date_sk FROM dim_date WHERE date_sk = ?", (today_int,))
        d_row = cursor.fetchone()
    if not d_row:
        cursor.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        d_row = cursor.fetchone()
    date_sk = d_row[0] if d_row else None

    cursor.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for r in cursor.fetchall():
        k = (bool(r[1]), bool(r[2]), bool(r[3]))
        platform_map[k] = r[0]

    def is_invalid(val):
        if val is None:
            return True
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            return False
        return pd.isna(val)

    def to_int(val, default=0):
        if is_invalid(val):
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def to_float(val, default=0.0):
        if is_invalid(val):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def parse_genres(val):
        if is_invalid(val):
            return []
        if isinstance(val, (list, tuple, np.ndarray)):
            return [str(x).strip() for x in val if x is not None and str(x).strip()]
        if isinstance(val, str):
            v = val.strip()
            if not v or v == '[]':
                return []
            if v.startswith('[') and v.endswith(']'):
                try:
                    parsed = ast.literal_eval(v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if x is not None and str(x).strip()]
                except Exception:
                    pass
            return [x.strip() for x in v.split(',') if x.strip()]
        return []

    def parse_date(val):
        if is_invalid(val):
            return None
        try:
            dt = pd.to_datetime(val)
            if pd.isna(dt):
                return None
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None

    def parse_owners(val):
        if is_invalid(val):
            return None, None, None
        s = str(val).strip()
        if not s:
            return None, None, None
        min_o, max_o = None, None
        if '-' in s:
            parts = s.split('-')
            try:
                min_o = int(parts[0].strip().replace(',', ''))
                max_o = int(parts[1].strip().replace(',', ''))
            except Exception:
                pass
        return s, min_o, max_o

    game_rows = []
    genre_set = set()
    row_genres_map = []
    fact_rows_raw = []

    for _, row in df.iterrows():
        app_id_val = row.get('app_id')
        if is_invalid(app_id_val):
            continue
        app_id_str = str(app_id_val).strip()
        if not app_id_str or app_id_str.lower() in ('nan', 'none', 'null'):
            continue

        name = str(row.get('name', '')).strip() if not is_invalid(row.get('name')) else None
        req_age = to_int(row.get('required_age'), 0)
        rel_date = parse_date(row.get('release_date'))
        est_owners, min_o, max_o = parse_owners(row.get('estimated_owners'))

        game_rows.append((app_id_str, name, req_age, rel_date, est_owners, min_o, max_o))

        genres = parse_genres(row.get('genres'))
        for g in genres:
            genre_set.add(g)
        row_genres_map.append((app_id_str, genres))

        win = bool(row.get('windows')) if not is_invalid(row.get('windows')) else False
        mac = bool(row.get('mac')) if not is_invalid(row.get('mac')) else False
        lin = bool(row.get('linux')) if not is_invalid(row.get('linux')) else False
        plat_sk = platform_map.get((win, mac, lin))

        price = to_float(row.get('price'), 0.0)
        discount = to_int(row.get('discount'), 0)
        peak_ccu = to_int(row.get('peak_ccu'), 0)
        pos = to_int(row.get('positive'), 0)
        neg = to_int(row.get('negative'), 0)
        playtime = to_int(row.get('average_playtime_forever'), 0)

        fact_rows_raw.append((app_id_str, plat_sk, price, discount, peak_ccu, pos, neg, playtime))

    genre_inserted_count = 0
    if genre_set:
        genre_tuples = [(g,) for g in genre_set]
        cursor.executemany("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", genre_tuples)
        genre_inserted_count = cursor.rowcount if cursor.rowcount >= 0 else len(genre_tuples)

    cursor.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_map = {r[0]: r[1] for r in cursor.fetchall()}

    game_inserted_count = 0
    if game_rows:
        cursor.executemany(
            """INSERT OR REPLACE INTO dim_game
               (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            game_rows
        )
        game_inserted_count = cursor.rowcount if cursor.rowcount >= 0 else len(game_rows)

    cursor.execute("SELECT app_id, game_sk FROM dim_game")
    game_map = {str(r[0]): r[1] for r in cursor.fetchall()}

    bridge_rows = []
    for app_id_str, genres in row_genres_map:
        g_sk = game_map.get(app_id_str)
        if g_sk:
            for g_name in genres:
                gn_sk = genre_map.get(g_name)
                if gn_sk:
                    bridge_rows.append((g_sk, gn_sk))

    bridge_inserted_count = 0
    if bridge_rows:
        cursor.executemany("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", bridge_rows)
        bridge_inserted_count = cursor.rowcount if cursor.rowcount >= 0 else len(bridge_rows)

    fact_rows = []
    for app_id_str, plat_sk, price, discount, peak_ccu, pos, neg, playtime in fact_rows_raw:
        g_sk = game_map.get(app_id_str)
        if g_sk:
            fact_rows.append((g_sk, date_sk, plat_sk, price, discount, peak_ccu, pos, neg, playtime))

    fact_inserted_count = 0
    if fact_rows:
        cursor.executemany(
            """INSERT INTO fact_game
               (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            fact_rows
        )
        fact_inserted_count = cursor.rowcount if cursor.rowcount >= 0 else len(fact_rows)

    return {
        "dim_game": game_inserted_count,
        "dim_genre": genre_inserted_count,
        "bridge_game_genre": bridge_inserted_count,
        "fact_game": fact_inserted_count
    }