import pandas as pd
import numpy as np
import json
import ast
import datetime

def run_etl(df, conn):
    cur = conn.cursor()

    def safe_clean(val):
        if val is None:
            return None
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            return None
        try:
            if pd.isna(val):
                return None
        except Exception:
            pass
        return val

    def safe_str(val):
        cleaned = safe_clean(val)
        if cleaned is None:
            return None
        s = str(cleaned).strip()
        if not s or s.lower() in ('none', 'nan', 'null', 'nat'):
            return None
        return s

    def safe_int(val, default=None):
        cleaned = safe_clean(val)
        if cleaned is None:
            return default
        try:
            return int(float(cleaned))
        except (ValueError, TypeError):
            return default

    def safe_float(val, default=None):
        cleaned = safe_clean(val)
        if cleaned is None:
            return default
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return default

    def to_bool(val):
        if val is None:
            return False
        if isinstance(val, (list, tuple, np.ndarray, dict)):
            return False
        try:
            if pd.isna(val):
                return False
        except Exception:
            pass
        if isinstance(val, (bool, np.bool_)):
            return bool(val)
        if isinstance(val, (int, float, np.number)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ('true', '1', 't', 'yes')
        return False

    def parse_date(val):
        s = safe_str(val)
        if not s:
            return None
        try:
            dt = pd.to_datetime(s, errors='coerce')
            if pd.notna(dt):
                return dt.strftime('%Y-%m-%d')
        except Exception:
            pass
        return s

    def parse_genres(val):
        if val is None:
            return []
        if isinstance(val, (list, tuple, np.ndarray)):
            res = []
            for item in val:
                if item is not None and not isinstance(item, (list, tuple, np.ndarray, dict)):
                    s = str(item).strip()
                    if s:
                        res.append(s)
            return res
        if isinstance(val, dict):
            return [str(k).strip() for k in val.keys() if k and str(k).strip()]
        try:
            if pd.isna(val):
                return []
        except Exception:
            pass
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return []
            if (s.startswith('[') and s.endswith(']')) or (s.startswith('{') and s.endswith('}')):
                try:
                    parsed = ast.literal_eval(s)
                    if isinstance(parsed, (list, tuple)):
                        return [str(x).strip() for x in parsed if x and str(x).strip()]
                    elif isinstance(parsed, dict):
                        return [str(k).strip() for k in parsed.keys() if k and str(k).strip()]
                except Exception:
                    pass
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, (list, tuple)):
                        return [str(x).strip() for x in parsed if x and str(x).strip()]
                    elif isinstance(parsed, dict):
                        return [str(k).strip() for k in parsed.keys() if k and str(k).strip()]
                except Exception:
                    pass
                inner = s[1:-1]
                return [g.strip(" '\"") for g in inner.split(',') if g.strip(" '\"")]
            else:
                return [g.strip() for g in s.split(',') if g.strip()]
        return []

    def parse_owners(row_data):
        est = safe_str(row_data.get('estimated_owners'))
        o_min = safe_int(row_data.get('owners_min'))
        o_max = safe_int(row_data.get('owners_max'))
        if (o_min is None or o_max is None) and est:
            parts = est.split('-')
            if len(parts) == 2:
                try:
                    if o_min is None:
                        o_min = int(parts[0].replace(',', '').strip())
                    if o_max is None:
                        o_max = int(parts[1].replace(',', '').strip())
                except Exception:
                    pass
        return est, o_min, o_max

    today_dt = datetime.date.today()
    today_iso = today_dt.isoformat()
    today_int = int(today_dt.strftime('%Y%m%d'))

    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = ? OR date_sk = ? LIMIT 1", (today_iso, today_int))
    row = cur.fetchone()
    if row:
        date_sk = row[0]
    else:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
        row = cur.fetchone()
        date_sk = row[0] if row else 1

    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cur.fetchall():
        platform_map[(bool(w), bool(m), bool(l))] = p_sk
    default_p_sk = next(iter(platform_map.values())) if platform_map else 1

    cur.execute("SELECT COUNT(*) FROM dim_genre")
    dim_genre_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM dim_game")
    dim_game_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bridge_game_genre")
    bridge_before = cur.fetchone()[0]

    valid_rows = []
    genres_set = set()

    for idx, row_data in df.iterrows():
        app_id = safe_str(row_data.get('app_id'))
        if not app_id:
            continue
        valid_rows.append(row_data)
        for g in parse_genres(row_data.get('genres')):
            genres_set.add(g)

    if genres_set:
        cur.executemany("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", [(g,) for g in genres_set])

    cur.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_map = {r[0]: r[1] for r in cur.fetchall()}

    game_insert_tuples = []
    seen_apps = set()
    for row_data in valid_rows:
        app_id = safe_str(row_data.get('app_id'))
        if app_id in seen_apps:
            continue
        seen_apps.add(app_id)
        game_name = safe_str(row_data.get('name')) or safe_str(row_data.get('game_name'))
        req_age = safe_int(row_data.get('required_age'), 0)
        rel_date = parse_date(row_data.get('release_date'))
        est_owners, o_min, o_max = parse_owners(row_data)
        game_insert_tuples.append((app_id, game_name, req_age, rel_date, est_owners, o_min, o_max))

    if game_insert_tuples:
        cur.executemany("""
            INSERT OR IGNORE INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, game_insert_tuples)

    cur.execute("SELECT app_id, game_sk FROM dim_game")
    game_sk_map = {str(r[0]): r[1] for r in cur.fetchall()}

    bridge_tuples = set()
    fact_tuples = []

    for row_data in valid_rows:
        app_id = safe_str(row_data.get('app_id'))
        game_sk = game_sk_map.get(app_id)
        if not game_sk:
            continue

        for g in parse_genres(row_data.get('genres')):
            g_sk = genre_map.get(g)
            if g_sk:
                bridge_tuples.add((game_sk, g_sk))

        win = to_bool(row_data.get('windows'))
        mac = to_bool(row_data.get('mac'))
        lin = to_bool(row_data.get('linux'))
        p_sk = platform_map.get((win, mac, lin), default_p_sk)

        price = safe_float(row_data.get('price'))
        if price is None:
            price = safe_float(row_data.get('price_usd'))

        discount = safe_int(row_data.get('discount'))
        if discount is None:
            discount = safe_int(row_data.get('discount_pct'))

        peak_ccu = safe_int(row_data.get('peak_ccu'))

        pos_rev = safe_int(row_data.get('positive'))
        if pos_rev is None:
            pos_rev = safe_int(row_data.get('positive_reviews'))

        neg_rev = safe_int(row_data.get('negative'))
        if neg_rev is None:
            neg_rev = safe_int(row_data.get('negative_reviews'))

        playtime = safe_int(row_data.get('average_playtime_forever'))
        if playtime is None:
            playtime = safe_int(row_data.get('average_playtime_mins'))

        fact_tuples.append((
            game_sk, date_sk, p_sk, price, discount, peak_ccu, pos_rev, neg_rev, playtime
        ))

    if bridge_tuples:
        cur.executemany("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", list(bridge_tuples))

    if fact_tuples:
        cur.executemany("""
            INSERT OR REPLACE INTO fact_game (
                game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, fact_tuples)

    cur.execute("SELECT COUNT(*) FROM dim_genre")
    dim_genre_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM dim_game")
    dim_game_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bridge_game_genre")
    bridge_after = cur.fetchone()[0]

    return {
        "dim_genre": dim_genre_after - dim_genre_before,
        "dim_game": dim_game_after - dim_game_before,
        "bridge_game_genre": bridge_after - bridge_before,
        "fact_game": len(fact_tuples)
    }