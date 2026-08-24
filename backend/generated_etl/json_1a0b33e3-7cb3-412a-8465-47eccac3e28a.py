import ast
import json
from datetime import datetime
import pandas as pd
import numpy as np


def run_etl(df, conn):
    def parse_val(val):
        if pd.isna(val) or val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            val_s = val.strip()
            if (val_s.startswith('{') and val_s.endswith('}')) or (val_s.startswith('[') and val_s.endswith(']')):
                try:
                    return ast.literal_eval(val_s)
                except Exception:
                    try:
                        return json.loads(val_s)
                    except Exception:
                        pass
        return val

    def get_field(row_dict, keys, pos):
        for k in keys:
            if k in row_dict and pd.notna(row_dict[k]):
                return row_dict[k]
        if pos is not None and pos in row_dict and pd.notna(row_dict[pos]):
            return row_dict[pos]
        return None

    def to_int(v):
        if v is None or pd.isna(v):
            return None
        try:
            return int(v)
        except Exception:
            return None

    def to_float(v):
        if v is None or pd.isna(v):
            return None
        try:
            return float(v)
        except Exception:
            return None

    cur = conn.cursor()

    today_str = datetime.now().strftime("%Y-%m-%d")
    today_int = int(datetime.now().strftime("%Y%m%d"))
    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = ? OR date_sk = ?", (today_str, today_int))
    row = cur.fetchone()
    if row:
        date_sk = row[0]
    else:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        row = cur.fetchone()
        date_sk = row[0] if row else today_int

    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cur.fetchall():
        platform_map[(bool(w), bool(m), bool(l))] = p_sk
    default_platform_sk = list(platform_map.values())[0] if platform_map else 1

    if any(k in df.index for k in ['name', 'game_name', 'release_date', 'genres', 'platforms', 'price', 'owners', 'stats']):
        df = df.T
    elif len(df.index) <= 12 and len(df.columns) > len(df.index) and not any(k in df.columns for k in ['app_id', 'game_name', 'name', 'release_date']):
        df = df.T

    records = df.to_dict('records')

    dim_game_rows = []
    all_genre_names = set()
    game_genres_list = []
    fact_data_list = []

    for r in records:
        raw_app_id = get_field(r, ['app_id', 'id'], 0)
        if raw_app_id is None or pd.isna(raw_app_id):
            continue
        app_id = str(raw_app_id).strip()
        if not app_id:
            continue

        raw_name = get_field(r, ['game_name', 'name', 'title'], 1)
        game_name = str(raw_name).strip() if raw_name is not None and pd.notna(raw_name) else None

        raw_rel_date = get_field(r, ['release_date', 'date'], 2)
        release_date = str(raw_rel_date).strip() if raw_rel_date is not None and pd.notna(raw_rel_date) else None

        req_age = to_int(get_field(r, ['required_age', 'age'], 3))
        required_age = req_age if req_age is not None else 0

        raw_price = get_field(r, ['price', 'price_info', 'pricing'], 4)
        price_dict = parse_val(raw_price)
        if isinstance(price_dict, dict):
            price_usd = to_float(price_dict.get('base_price_usd') or price_dict.get('price_usd'))
            discount_pct = to_int(price_dict.get('current_discount_pct') or price_dict.get('discount_pct'))
        else:
            price_usd = to_float(get_field(r, ['price_usd', 'base_price_usd'], None))
            discount_pct = to_int(get_field(r, ['discount_pct', 'current_discount_pct'], None))

        raw_owners = get_field(r, ['owners', 'estimated_owners', 'owners_info'], 5)
        owners_dict = parse_val(raw_owners)
        owners_min, owners_max, estimated_owners = None, None, None
        if isinstance(owners_dict, dict):
            owners_min = to_int(owners_dict.get('min') or owners_dict.get('owners_min'))
            owners_max = to_int(owners_dict.get('max') or owners_dict.get('owners_max'))
            estimated_owners = owners_dict.get('estimated_owners')
            if not estimated_owners and owners_min is not None and owners_max is not None:
                estimated_owners = f"{owners_min} - {owners_max}"
        elif isinstance(raw_owners, str) and not raw_owners.startswith('{'):
            estimated_owners = raw_owners

        raw_plat = get_field(r, ['platforms', 'platform_support', 'os'], 6)
        plat_dict = parse_val(raw_plat)
        if isinstance(plat_dict, dict):
            win = bool(plat_dict.get('windows', False))
            mac = bool(plat_dict.get('mac', False))
            lin = bool(plat_dict.get('linux', False))
        else:
            win, mac, lin = True, False, False
        platform_sk = platform_map.get((win, mac, lin), default_platform_sk)

        raw_stats = get_field(r, ['stats', 'metrics', 'user_stats'], 7)
        stats_dict = parse_val(raw_stats)
        if isinstance(stats_dict, dict):
            peak_ccu = to_int(stats_dict.get('peak_concurrent_users') or stats_dict.get('peak_ccu'))
            positive_reviews = to_int(stats_dict.get('reviews_positive') or stats_dict.get('positive_reviews'))
            negative_reviews = to_int(stats_dict.get('reviews_negative') or stats_dict.get('negative_reviews'))
            avg_playtime = to_int(stats_dict.get('avg_playtime_minutes') or stats_dict.get('average_playtime_mins'))
        else:
            peak_ccu = to_int(get_field(r, ['peak_concurrent_users', 'peak_ccu'], None))
            positive_reviews = to_int(get_field(r, ['reviews_positive', 'positive_reviews'], None))
            negative_reviews = to_int(get_field(r, ['reviews_negative', 'negative_reviews'], None))
            avg_playtime = to_int(get_field(r, ['avg_playtime_minutes', 'average_playtime_mins'], None))

        raw_genres = get_field(r, ['genres', 'genre_list'], 8)
        genres_val = parse_val(raw_genres)
        genre_list = []
        if isinstance(genres_val, list):
            genre_list = [str(g).strip() for g in genres_val if g and pd.notna(g)]
        elif isinstance(genres_val, str):
            genre_list = [g.strip() for g in genres_val.split(',') if g.strip()]

        for g in genre_list:
            all_genre_names.add(g)

        dim_game_rows.append((app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max))
        game_genres_list.append((app_id, genre_list))
        fact_data_list.append({
            'app_id': app_id,
            'platform_sk': platform_sk,
            'price_usd': price_usd,
            'discount_pct': discount_pct,
            'peak_ccu': peak_ccu,
            'positive_reviews': positive_reviews,
            'negative_reviews': negative_reviews,
            'average_playtime_mins': avg_playtime
        })

    cur.executemany("""
        INSERT OR REPLACE INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, dim_game_rows)

    cur.execute("SELECT app_id, game_sk FROM dim_game")
    game_sk_map = {str(app_id): g_sk for app_id, g_sk in cur.fetchall()}

    cur.execute("SELECT COUNT(*) FROM dim_genre")
    genre_count_before = cur.fetchone()[0]

    for g_name in all_genre_names:
        cur.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", (g_name,))

    cur.execute("SELECT COUNT(*) FROM dim_genre")
    genre_count_after = cur.fetchone()[0]
    dim_genre_inserted = genre_count_after - genre_count_before

    cur.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_sk_map = {g_name: g_sk for g_name, g_sk in cur.fetchall()}

    cur.execute("SELECT COUNT(*) FROM bridge_game_genre")
    bridge_before = cur.fetchone()[0]

    bridge_rows = []
    for app_id, genres in game_genres_list:
        g_sk = game_sk_map.get(str(app_id))
        if g_sk:
            for g_name in genres:
                gn_sk = genre_sk_map.get(g_name)
                if gn_sk:
                    bridge_rows.append((g_sk, gn_sk))

    cur.executemany("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", bridge_rows)

    cur.execute("SELECT COUNT(*) FROM bridge_game_genre")
    bridge_after = cur.fetchone()[0]
    bridge_inserted = bridge_after - bridge_before

    fact_rows = []
    for item in fact_data_list:
        g_sk = game_sk_map.get(str(item['app_id']))
        if g_sk:
            fact_rows.append((
                g_sk,
                date_sk,
                item['platform_sk'],
                item['price_usd'],
                item['discount_pct'],
                item['peak_ccu'],
                item['positive_reviews'],
                item['negative_reviews'],
                item['average_playtime_mins']
            ))

    cur.executemany("""
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, fact_rows)

    return {
        "dim_date": 0,
        "dim_platform": 0,
        "dim_game": len(dim_game_rows),
        "dim_genre": dim_genre_inserted,
        "bridge_game_genre": bridge_inserted,
        "fact_game": len(fact_rows)
    }