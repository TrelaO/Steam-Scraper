import ast
import datetime
import numpy as np
import pandas as pd


def run_etl(df, conn):
    cursor = conn.cursor()

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    cursor.execute("SELECT date_sk FROM dim_date WHERE full_date = ?", (today_str,))
    d_row = cursor.fetchone()
    if not d_row:
        cursor.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        d_row = cursor.fetchone()
    if not d_row:
        cursor.execute("SELECT date_sk FROM dim_date LIMIT 1")
        d_row = cursor.fetchone()
    date_sk = d_row[0] if d_row else None

    cursor.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cursor.fetchall():
        platform_map[(bool(w), bool(m), bool(l))] = p_sk
    default_platform_sk = next(iter(platform_map.values()), None) if platform_map else None

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0,
    }

    def safe_bool(val):
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            return False
        if val is None or pd.isna(val):
            return False
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "t", "yes")
        return bool(val)

    def safe_int(val, default=0):
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            return default
        if val is None or pd.isna(val):
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def safe_float(val, default=0.0):
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            return default
        if val is None or pd.isna(val):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def parse_genres(val):
        if isinstance(val, (list, tuple, np.ndarray)):
            res = []
            for item in val:
                if isinstance(item, (list, tuple, np.ndarray)):
                    res.extend(parse_genres(item))
                elif isinstance(item, dict):
                    g = item.get('description') or item.get('name') or item.get('genre')
                    if g and not isinstance(g, (list, tuple, np.ndarray, dict)):
                        res.append(str(g).strip())
                elif item is not None and not pd.isna(item):
                    res.append(str(item).strip())
            return res
        if isinstance(val, dict):
            g = val.get('description') or val.get('name') or val.get('genre')
            if g and not isinstance(g, (list, tuple, np.ndarray, dict)):
                return [str(g).strip()]
            return []
        if val is None or pd.isna(val):
            return []
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return []
            if (s.startswith('[') and s.endswith(']')) or (s.startswith('{') and s.endswith('}')):
                try:
                    parsed = ast.literal_eval(s)
                    return parse_genres(parsed)
                except Exception:
                    pass
            cleaned = s.replace('[', '').replace(']', '').replace("'", "").replace('"', '')
            return [g.strip() for g in cleaned.split(',') if g.strip()]
        return []

    date_map = {}
    if 'release_date' in df.columns:
        for r in df['release_date'].dropna().unique():
            if isinstance(r, (list, tuple, np.ndarray, dict)):
                continue
            if r is None or pd.isna(r):
                continue
            try:
                dt = pd.to_datetime(r)
                if not pd.isna(dt):
                    date_map[r] = dt.strftime('%Y-%m-%d')
                else:
                    date_map[r] = str(r).strip()
            except Exception:
                date_map[r] = str(r).strip()

    records = df.to_dict('records')

    all_genres = set()
    parsed_records = []

    for row in records:
        app_id_raw = row.get('app_id')
        if isinstance(app_id_raw, (list, tuple, np.ndarray, dict)):
            continue
        if app_id_raw is None or pd.isna(app_id_raw):
            continue
        app_id = str(app_id_raw).strip()
        if not app_id or app_id.lower() in ('nan', 'none', 'null'):
            continue

        name_raw = row.get('name')
        if isinstance(name_raw, (list, tuple, np.ndarray, dict)) or name_raw is None or pd.isna(name_raw):
            game_name = None
        else:
            game_name = str(name_raw).strip()

        required_age = safe_int(row.get('required_age'), 0)

        rel_raw = row.get('release_date')
        release_date = None
        if not isinstance(rel_raw, (list, tuple, np.ndarray, dict)) and rel_raw is not None and not pd.isna(rel_raw):
            release_date = date_map.get(rel_raw, str(rel_raw).strip())

        owners_raw = row.get('estimated_owners')
        estimated_owners = None
        owners_min, owners_max = None, None
        if not isinstance(owners_raw, (list, tuple, np.ndarray, dict)) and owners_raw is not None and not pd.isna(owners_raw):
            estimated_owners = str(owners_raw).strip()
            if '-' in estimated_owners:
                parts = estimated_owners.split('-')
                try:
                    owners_min = int(parts[0].strip().replace(',', ''))
                    owners_max = int(parts[1].strip().replace(',', ''))
                except Exception:
                    pass

        genre_list = parse_genres(row.get('genres'))
        for g in genre_list:
            if g:
                all_genres.add(g)

        win = safe_bool(row.get('windows'))
        mac = safe_bool(row.get('mac'))
        lin = safe_bool(row.get('linux'))
        p_sk = platform_map.get((win, mac, lin), default_platform_sk)

        price_usd = safe_float(row.get('price'), 0.0)
        discount_pct = safe_int(row.get('discount'), 0)
        peak_ccu = safe_int(row.get('peak_ccu'), 0)
        positive_reviews = safe_int(row.get('positive'), 0)
        negative_reviews = safe_int(row.get('negative'), 0)
        average_playtime_mins = safe_int(row.get('average_playtime_forever'), 0)

        parsed_records.append({
            'app_id': app_id,
            'game_name': game_name,
            'required_age': required_age,
            'release_date': release_date,
            'estimated_owners': estimated_owners,
            'owners_min': owners_min,
            'owners_max': owners_max,
            'genre_list': genre_list,
            'platform_sk': p_sk,
            'price_usd': price_usd,
            'discount_pct': discount_pct,
            'peak_ccu': peak_ccu,
            'positive_reviews': positive_reviews,
            'negative_reviews': negative_reviews,
            'average_playtime_mins': average_playtime_mins
        })

    if all_genres:
        c_before = conn.total_changes
        cursor.executemany(
            "INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)",
            [(g,) for g in all_genres]
        )
        counts["dim_genre"] += (conn.total_changes - c_before)

    cursor.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_map = dict(cursor.fetchall())

    games_to_insert = [
        (
            item['app_id'], item['game_name'], item['required_age'], item['release_date'],
            item['estimated_owners'], item['owners_min'], item['owners_max']
        )
        for item in parsed_records
    ]

    if games_to_insert:
        c_before = conn.total_changes
        cursor.executemany(
            """
            INSERT OR IGNORE INTO dim_game 
            (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            games_to_insert
        )
        counts["dim_game"] += (conn.total_changes - c_before)

    cursor.execute("SELECT app_id, game_sk FROM dim_game")
    game_map = dict(cursor.fetchall())

    bridges_to_insert = set()
    facts_to_insert = []

    for item in parsed_records:
        g_sk = game_map.get(item['app_id'])
        if not g_sk:
            continue

        for g_name in item['genre_list']:
            gn_sk = genre_map.get(g_name)
            if gn_sk:
                bridges_to_insert.add((g_sk, gn_sk))

        facts_to_insert.append((
            g_sk, date_sk, item['platform_sk'], item['price_usd'], item['discount_pct'],
            item['peak_ccu'], item['positive_reviews'], item['negative_reviews'], item['average_playtime_mins']
        ))

    if bridges_to_insert:
        c_before = conn.total_changes
        cursor.executemany(
            "INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)",
            list(bridges_to_insert)
        )
        counts["bridge_game_genre"] += (conn.total_changes - c_before)

    if facts_to_insert:
        c_before = conn.total_changes
        cursor.executemany(
            """
            INSERT INTO fact_game 
            (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            facts_to_insert
        )
        counts["fact_game"] += (conn.total_changes - c_before)

    return counts