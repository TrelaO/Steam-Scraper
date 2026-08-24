import pandas as pd

def run_etl(df, conn):
    cur = conn.cursor()

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0
    }

    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = DATE('now')")
    date_row = cur.fetchone()
    if not date_row:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        date_row = cur.fetchone()
    date_sk = date_row[0] if date_row else 1

    def parse_bool(val):
        if val is None or pd.isna(val):
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        s = str(val).strip().lower()
        return s in ('tak', 'true', '1', 'yes', 't', 'y')

    def safe_int(val, default=0):
        if val is None or pd.isna(val):
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def safe_float(val, default=0.0):
        if val is None or pd.isna(val):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_val(row, *keys):
        for k in keys:
            if k in row and not pd.isna(row[k]):
                return row[k]
        return None

    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cur.fetchall():
        platform_map[(parse_bool(w), parse_bool(m), parse_bool(l))] = p_sk

    for _, row in df.iterrows():
        app_id_raw = get_val(row, 'ID aplikacji', 'app_id', 'AppID')
        if app_id_raw is None or str(app_id_raw).strip() in ('', 'nan', 'None'):
            continue

        try:
            app_id = str(int(float(app_id_raw)))
        except (ValueError, TypeError):
            app_id = str(app_id_raw).strip()

        game_name_val = get_val(row, 'Nazwa gry', 'game_name', 'Name')
        game_name = str(game_name_val).strip() if game_name_val is not None else 'Unknown'

        release_date_val = get_val(row, 'Data premiery', 'release_date', 'Release date')
        if release_date_val is not None:
            release_date = str(release_date_val).strip()
            if 'T' in release_date:
                release_date = release_date.split('T')[0]
            elif ' ' in release_date:
                release_date = release_date.split(' ')[0]
        else:
            release_date = None

        required_age = safe_int(get_val(row, 'Wiek minimalny', 'required_age', 'Required age'), 0)
        owners_min = safe_int(get_val(row, 'Szacowani właściciele (min)', 'owners_min', 'Estimated owners min'), 0)
        owners_max = safe_int(get_val(row, 'Szacowani właściciele (max)', 'owners_max', 'Estimated owners max'), 0)

        estimated_owners_val = get_val(row, 'Szacowani właściciele', 'estimated_owners')
        if estimated_owners_val is not None:
            estimated_owners = str(estimated_owners_val).strip()
        else:
            estimated_owners = f"{owners_min} - {owners_max}"

        cur.execute("""
            INSERT OR IGNORE INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max))
        if cur.rowcount > 0:
            counts["dim_game"] += cur.rowcount

        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        game_sk_row = cur.fetchone()
        if not game_sk_row:
            continue
        game_sk = game_sk_row[0]

        genres_raw = get_val(row, 'Gatunki', 'genres', 'Genres')
        if genres_raw is not None:
            genre_list = [g.strip() for g in str(genres_raw).split(',') if g.strip()]
            for genre_name in genre_list:
                cur.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", (genre_name,))
                if cur.rowcount > 0:
                    counts["dim_genre"] += cur.rowcount

                cur.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (genre_name,))
                g_sk_row = cur.fetchone()
                if g_sk_row:
                    genre_sk = g_sk_row[0]
                    cur.execute("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, genre_sk))
                    if cur.rowcount > 0:
                        counts["bridge_game_genre"] += cur.rowcount

        win = parse_bool(get_val(row, 'Windows', 'windows', 'win', 'supports_windows'))
        mac = parse_bool(get_val(row, 'Mac', 'mac', 'supports_mac'))
        lin = parse_bool(get_val(row, 'Linux', 'linux', 'supports_linux'))
        platform_sk = platform_map.get((win, mac, lin))

        price_usd = safe_float(get_val(row, 'Cena (PLN)', 'price_usd', 'Price'), 0.0)
        discount_pct = safe_int(get_val(row, 'Zniżka (%)', 'discount_pct', 'Discount'), 0)
        peak_ccu = safe_int(get_val(row, 'Szczyt graczy jednocześnie', 'peak_ccu', 'Peak CCU'), 0)
        positive_reviews = safe_int(get_val(row, 'Recenzje pozytywne', 'positive_reviews', 'Positive'), 0)
        negative_reviews = safe_int(get_val(row, 'Recenzje negatywne', 'negative_reviews', 'Negative'), 0)

        playtime_mins_raw = get_val(row, 'average_playtime_mins', 'playtime_mins')
        if playtime_mins_raw is not None:
            average_playtime_mins = safe_int(playtime_mins_raw, 0)
        else:
            playtime_hours_raw = get_val(row, 'Śr. czas gry (godziny)', 'playtime_hours')
            average_playtime_mins = safe_int(safe_float(playtime_hours_raw, 0.0) * 60, 0)

        cur.execute("""
            INSERT INTO fact_game (
                game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu,
                positive_reviews, negative_reviews, average_playtime_mins
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu,
              positive_reviews, negative_reviews, average_playtime_mins))
        if cur.rowcount > 0:
            counts["fact_game"] += cur.rowcount

    return counts