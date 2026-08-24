import re
import pandas as pd

def run_etl(df, conn):
    cursor = conn.cursor()
    
    empty_result = {"dim_game": 0, "dim_genre": 0, "bridge_game_genre": 0, "fact_game": 0}
    if df is None or df.empty:
        return empty_result

    def find_col(candidates):
        cols_lower = {str(c).lower(): c for c in df.columns}
        for cand in candidates:
            if cand.lower() in cols_lower:
                return cols_lower[cand.lower()]
        return None

    appid_col = find_col(['appid', 'app_id', 'id'])
    if not appid_col:
        return empty_result

    df_clean = df.dropna(subset=[appid_col]).copy()
    df_clean = df_clean[df_clean[appid_col].astype(str).str.strip() != '']
    if df_clean.empty:
        return empty_result

    name_col = find_col(['name', 'game_name', 'title'])
    req_age_col = find_col(['required_age', 'required age', 'age'])
    rel_date_col = find_col(['release date', 'release_date', 'released'])
    est_owners_col = find_col(['estimated_owners', 'estimated owners', 'owners'])
    owners_min_col = find_col(['owners_min', 'owners min', 'min_owners'])
    owners_max_col = find_col(['owners_max', 'owners max', 'max_owners'])
    genres_col = find_col(['genres', 'genre'])
    win_col = find_col(['windows', 'win'])
    mac_col = find_col(['mac', 'macintosh', 'os x', 'osx'])
    lin_col = find_col(['linux', 'lin'])
    price_col = find_col(['price', 'price_usd'])
    disc_col = find_col(['discount', 'discount_pct', 'discount pct'])
    ccu_col = find_col(['peak ccu', 'peak_ccu', 'ccu'])
    pos_col = find_col(['positive', 'positive_reviews', 'positive reviews'])
    neg_col = find_col(['negative', 'negative_reviews', 'negative reviews'])
    playtime_col = find_col(['average playtime forever', 'average_playtime_mins', 'average playtime', 'playtime_forever'])

    def safe_val(row, col):
        if col and col in row and pd.notna(row[col]):
            return row[col]
        return None

    def safe_bool(val):
        if val is None or pd.isna(val):
            return False
        if isinstance(val, (bool, int, float)):
            return bool(val)
        return str(val).strip().lower() in ('true', '1', 't', 'yes')

    def safe_int(val):
        if val is None or pd.isna(val):
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    def safe_float(val):
        if val is None or pd.isna(val):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def parse_date_str(val):
        if val is None or pd.isna(val):
            return None
        val_str = str(val).strip()
        if not val_str:
            return None
        m = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', val_str)
        if m:
            y, m_str, d = m.groups()
            return f"{int(y):04d}-{int(m_str):02d}-{int(d):02d}"
        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
            'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
            'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
        }
        parts = re.split(r'[\s,]+', val_str)
        if len(parts) >= 3:
            m_val, y_val, d_val = None, None, None
            for p in parts:
                p_lower = p.lower()
                if p_lower in months:
                    m_val = months[p_lower]
                elif p.isdigit():
                    num = int(p)
                    if num > 1000:
                        y_val = num
                    elif num <= 31:
                        if d_val is None:
                            d_val = num
            if y_val and m_val and d_val:
                return f"{y_val:04d}-{m_val:02d}-{d_val:02d}"
        return val_str[:10] if len(val_str) >= 10 else val_str

    cursor.execute("SELECT date_sk FROM dim_date WHERE full_date = date('now') LIMIT 1")
    res = cursor.fetchone()
    if not res:
        cursor.execute("SELECT date_sk FROM dim_date WHERE full_date <= date('now') ORDER BY full_date DESC LIMIT 1")
        res = cursor.fetchone()
    if not res:
        cursor.execute("SELECT date_sk FROM dim_date ORDER BY full_date DESC LIMIT 1")
        res = cursor.fetchone()
    date_sk = res[0] if res else None

    cursor.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cursor.fetchall():
        platform_map[(bool(w), bool(m), bool(l))] = p_sk

    dim_game_records = []
    genre_set = set()
    game_genres_pairs = []
    fact_records = []

    for _, row in df_clean.iterrows():
        app_id = str(row[appid_col]).strip()
        name_val = safe_val(row, name_col)
        game_name = str(name_val) if name_val is not None else None
        req_age = safe_int(safe_val(row, req_age_col))

        rel_date_raw = safe_val(row, rel_date_col)
        rel_date = parse_date_str(rel_date_raw)

        est_owners_raw = safe_val(row, est_owners_col)
        est_owners = str(est_owners_raw) if est_owners_raw is not None else None
        owners_min = safe_int(safe_val(row, owners_min_col))
        owners_max = safe_int(safe_val(row, owners_max_col))

        dim_game_records.append((app_id, game_name, req_age, rel_date, est_owners, owners_min, owners_max))

        genres_raw = safe_val(row, genres_col)
        if genres_raw is not None and not pd.isna(genres_raw):
            g_str = str(genres_raw).strip()
            if g_str:
                g_list = [g.strip() for g in re.split(r'[,;]', g_str) if g.strip() and g.strip().lower() != 'nan']
                for g in g_list:
                    genre_set.add(g)
                    game_genres_pairs.append((app_id, g))

        win = safe_bool(safe_val(row, win_col))
        mac = safe_bool(safe_val(row, mac_col))
        lin = safe_bool(safe_val(row, lin_col))
        p_sk = platform_map.get((win, mac, lin))

        price_usd = safe_float(safe_val(row, price_col))
        discount_pct = safe_int(safe_val(row, disc_col))
        peak_ccu = safe_int(safe_val(row, ccu_col))
        pos_rev = safe_int(safe_val(row, pos_col))
        neg_rev = safe_int(safe_val(row, neg_col))
        avg_playtime = safe_int(safe_val(row, playtime_col))

        fact_records.append((
            app_id,
            date_sk,
            p_sk,
            price_usd,
            discount_pct,
            peak_ccu,
            pos_rev,
            neg_rev,
            avg_playtime
        ))

    initial_game_count = cursor.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0]
    cursor.executemany("""
        INSERT OR IGNORE INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, dim_game_records)
    dim_game_inserted = cursor.execute("SELECT COUNT(*) FROM dim_game").fetchone()[0] - initial_game_count

    cursor.execute("SELECT app_id, game_sk FROM dim_game")
    game_sk_map = {str(row[0]): row[1] for row in cursor.fetchall()}

    initial_genre_count = cursor.execute("SELECT COUNT(*) FROM dim_genre").fetchone()[0]
    cursor.executemany("""
        INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)
    """, [(g,) for g in genre_set])
    dim_genre_inserted = cursor.execute("SELECT COUNT(*) FROM dim_genre").fetchone()[0] - initial_genre_count

    cursor.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_sk_map = {str(row[0]): row[1] for row in cursor.fetchall()}

    bridge_records = set()
    for app_id, g_name in game_genres_pairs:
        g_sk = game_sk_map.get(app_id)
        gen_sk = genre_sk_map.get(g_name)
        if g_sk and gen_sk:
            bridge_records.add((g_sk, gen_sk))

    initial_bridge_count = cursor.execute("SELECT COUNT(*) FROM bridge_game_genre").fetchone()[0]
    cursor.executemany("""
        INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)
    """, list(bridge_records))
    bridge_inserted = cursor.execute("SELECT COUNT(*) FROM bridge_game_genre").fetchone()[0] - initial_bridge_count

    fact_to_insert = []
    for f in fact_records:
        app_id = f[0]
        g_sk = game_sk_map.get(app_id)
        if g_sk:
            fact_to_insert.append((g_sk,) + f[1:])

    initial_fact_count = cursor.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0]
    cursor.executemany("""
        INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, fact_to_insert)
    fact_inserted = cursor.execute("SELECT COUNT(*) FROM fact_game").fetchone()[0] - initial_fact_count

    return {
        "dim_game": dim_game_inserted,
        "dim_genre": dim_genre_inserted,
        "bridge_game_genre": bridge_inserted,
        "fact_game": fact_inserted
    }