import datetime
import pandas as pd

def run_etl(df, conn):
    cur = conn.cursor()

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = ?", (today_str,))
    row = cur.fetchone()
    if row:
        date_sk = row[0]
    else:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY full_date DESC LIMIT 1")
        row = cur.fetchone()
        date_sk = row[0] if row else None

    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_rows = cur.fetchall()
    platform_map = {}
    for p_sk, w, m, l in platform_rows:
        platform_map[(bool(w), bool(m), bool(l))] = p_sk

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0
    }

    col_map = {str(c).strip().lower().replace(' ', '_').replace('-', '_'): c for c in df.columns}

    def get_val(row, *possible_keys, default=None):
        for key in possible_keys:
            k_clean = key.lower().replace(' ', '_').replace('-', '_')
            if k_clean in col_map:
                val = row[col_map[k_clean]]
                if pd.notna(val):
                    return val
        return default

    def parse_bool(val):
        if pd.isna(val) or val is None:
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        s = str(val).strip().lower()
        return s in ('true', '1', 't', 'yes', 'y', '1.0')

    def parse_int(val, default=0):
        if pd.isna(val) or val is None:
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def parse_float(val, default=0.0):
        if pd.isna(val) or val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def parse_date(val):
        if pd.isna(val) or val is None:
            return None
        s = str(val).strip()
        if not s or s.lower() == 'nan':
            return None
        try:
            dt = pd.to_datetime(s)
            if pd.isna(dt):
                return None
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None

    for _, row in df.iterrows():
        app_id_raw = get_val(row, 'appid', 'app_id')
        if app_id_raw is None or pd.isna(app_id_raw):
            continue
        app_id = str(app_id_raw).strip()
        if not app_id or app_id.lower() == 'nan':
            continue

        game_name = get_val(row, 'name', 'game_name')
        game_name = str(game_name).strip() if game_name is not None else None

        required_age = parse_int(get_val(row, 'required_age', 'age'), default=0)
        release_date = parse_date(get_val(row, 'release_date', 'released'))

        estimated_owners = get_val(row, 'estimated_owners', 'owners')
        owners_min, owners_max = None, None
        if estimated_owners is not None:
            estimated_owners = str(estimated_owners).strip()
            if '-' in estimated_owners:
                parts = estimated_owners.split('-')
                owners_min = parse_int(parts[0])
                owners_max = parse_int(parts[1])
        else:
            owners_min = parse_int(get_val(row, 'owners_min'))
            owners_max = parse_int(get_val(row, 'owners_max'))

        cur.execute(
            """
            INSERT OR IGNORE INTO dim_game 
            (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
        )
        if cur.rowcount > 0:
            counts["dim_game"] += cur.rowcount

        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        game_sk_row = cur.fetchone()
        if not game_sk_row:
            continue
        game_sk = game_sk_row[0]

        genres_raw = get_val(row, 'genres', 'genre')
        if genres_raw and pd.notna(genres_raw):
            genre_list = [g.strip() for g in str(genres_raw).split(',') if g.strip()]
            for g_name in genre_list:
                cur.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", (g_name,))
                if cur.rowcount > 0:
                    counts["dim_genre"] += cur.rowcount

                cur.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (g_name,))
                g_row = cur.fetchone()
                if g_row:
                    genre_sk = g_row[0]
                    cur.execute("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, genre_sk))
                    if cur.rowcount > 0:
                        counts["bridge_game_genre"] += cur.rowcount

        win = parse_bool(get_val(row, 'windows', 'supports_windows'))
        mac = parse_bool(get_val(row, 'mac', 'supports_mac'))
        lin = parse_bool(get_val(row, 'linux', 'supports_linux'))

        platform_sk = platform_map.get((win, mac, lin))
        if platform_sk is None and platform_map:
            platform_sk = list(platform_map.values())[0]

        price_usd = parse_float(get_val(row, 'price', 'price_usd'), default=0.0)
        discount_pct = parse_int(get_val(row, 'discount', 'discount_pct'), default=0)
        peak_ccu = parse_int(get_val(row, 'peak_ccu', 'peak_ccu_forever'), default=0)
        positive_reviews = parse_int(get_val(row, 'positive', 'positive_reviews'), default=0)
        negative_reviews = parse_int(get_val(row, 'negative', 'negative_reviews'), default=0)
        avg_playtime = parse_int(get_val(row, 'average_playtime_forever', 'average_playtime_mins', 'playtime'), default=0)

        cur.execute(
            """
            INSERT OR REPLACE INTO fact_game 
            (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, avg_playtime)
        )
        if cur.rowcount > 0:
            counts["fact_game"] += cur.rowcount

    return counts