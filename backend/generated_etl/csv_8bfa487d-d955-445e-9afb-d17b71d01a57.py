import pandas as pd

def safe_int(val):
    if pd.isna(val) or val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

def safe_float(val):
    if pd.isna(val) or val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def safe_str(val):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s else None

def safe_bool(val):
    if pd.isna(val) or val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val).strip().lower() in ("true", "1", "t", "yes")

def get_val(row, *cols):
    for col in cols:
        if col in row and pd.notna(row[col]):
            return row[col]
    return None

def run_etl(df, conn):
    cursor = conn.cursor()

    df = df.copy()

    today_str = pd.Timestamp.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT date_sk FROM dim_date WHERE full_date = ?", (today_str,))
    row = cursor.fetchone()
    if row:
        date_sk = row[0]
    else:
        cursor.execute("SELECT date_sk FROM dim_date WHERE full_date = DATE('now')")
        row = cursor.fetchone()
        if row:
            date_sk = row[0]
        else:
            cursor.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
            row = cursor.fetchone()
            date_sk = row[0] if row else None

    cursor.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cursor.fetchall():
        platform_map[(safe_bool(w), safe_bool(m), safe_bool(l))] = p_sk

    genres_set = set()
    for _, row in df.iterrows():
        g_val = get_val(row, 'Genres', 'genres', 'Genre', 'genre')
        if g_val:
            for g in str(g_val).split(','):
                g_clean = g.strip()
                if g_clean:
                    genres_set.add(g_clean)

    cursor.execute("SELECT COUNT(*) FROM dim_genre")
    genre_count_before = cursor.fetchone()[0]

    if genres_set:
        cursor.executemany(
            "INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)",
            [(g,) for g in sorted(genres_set)]
        )

    cursor.execute("SELECT COUNT(*) FROM dim_genre")
    genre_inserted = cursor.fetchone()[0] - genre_count_before

    cursor.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_map = {name: g_sk for name, g_sk in cursor.fetchall()}

    game_rows = []
    for _, row in df.iterrows():
        app_id = safe_str(get_val(row, 'AppID', 'app_id', 'appid'))
        if not app_id:
            continue
        game_name = safe_str(get_val(row, 'Name', 'game_name', 'name'))
        req_age = safe_int(get_val(row, 'Required age', 'required_age'))
        rel_date = safe_str(get_val(row, 'Release date', 'release_date'))
        est_owners = safe_str(get_val(row, 'Estimated owners', 'estimated_owners'))
        owners_min = safe_int(get_val(row, 'owners_min', 'Owners min'))
        owners_max = safe_int(get_val(row, 'owners_max', 'Owners max'))
        game_rows.append((app_id, game_name, req_age, rel_date, est_owners, owners_min, owners_max))

    cursor.execute("SELECT COUNT(*) FROM dim_game")
    game_count_before = cursor.fetchone()[0]

    if game_rows:
        cursor.executemany(
            """
            INSERT OR IGNORE INTO dim_game 
            (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            game_rows
        )

    cursor.execute("SELECT COUNT(*) FROM dim_game")
    game_inserted = cursor.fetchone()[0] - game_count_before

    cursor.execute("SELECT app_id, game_sk FROM dim_game")
    app_id_to_sk = {str(app_id): g_sk for app_id, g_sk in cursor.fetchall()}

    bridge_rows = []
    fact_rows = []

    for _, row in df.iterrows():
        app_id = safe_str(get_val(row, 'AppID', 'app_id', 'appid'))
        if not app_id or app_id not in app_id_to_sk:
            continue
        game_sk = app_id_to_sk[app_id]

        g_val = get_val(row, 'Genres', 'genres', 'Genre', 'genre')
        if g_val:
            for g in str(g_val).split(','):
                g_clean = g.strip()
                if g_clean in genre_map:
                    bridge_rows.append((game_sk, genre_map[g_clean]))

        win = safe_bool(get_val(row, 'Windows', 'windows', 'supports_windows'))
        mac = safe_bool(get_val(row, 'Mac', 'mac', 'supports_mac'))
        lin = safe_bool(get_val(row, 'Linux', 'linux', 'supports_linux'))
        plat_sk = platform_map.get((win, mac, lin))

        price = safe_float(get_val(row, 'Price', 'price', 'price_usd'))
        discount = safe_int(get_val(row, 'Discount', 'discount_pct', 'discount'))
        peak_ccu = safe_int(get_val(row, 'Peak CCU', 'peak_ccu'))
        pos_rev = safe_int(get_val(row, 'Positive', 'positive', 'positive_reviews'))
        neg_rev = safe_int(get_val(row, 'Negative', 'negative', 'negative_reviews'))
        playtime = safe_int(get_val(row, 'Average playtime forever', 'average_playtime_mins', 'average_playtime'))

        fact_rows.append((game_sk, date_sk, plat_sk, price, discount, peak_ccu, pos_rev, neg_rev, playtime))

    cursor.execute("SELECT COUNT(*) FROM bridge_game_genre")
    bridge_count_before = cursor.fetchone()[0]

    if bridge_rows:
        cursor.executemany(
            "INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)",
            bridge_rows
        )

    cursor.execute("SELECT COUNT(*) FROM bridge_game_genre")
    bridge_inserted = cursor.fetchone()[0] - bridge_count_before

    cursor.execute("SELECT COUNT(*) FROM fact_game")
    fact_count_before = cursor.fetchone()[0]

    if fact_rows:
        cursor.executemany(
            """
            INSERT INTO fact_game 
            (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fact_rows
        )

    cursor.execute("SELECT COUNT(*) FROM fact_game")
    fact_inserted = cursor.fetchone()[0] - fact_count_before

    return {
        "dim_game": game_inserted,
        "dim_genre": genre_inserted,
        "bridge_game_genre": bridge_inserted,
        "fact_game": fact_inserted
    }