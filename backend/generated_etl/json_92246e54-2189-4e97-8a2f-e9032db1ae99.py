import datetime
import ast
import json
import pandas as pd
import numpy as np

def run_etl(df, conn):
    cur = conn.cursor()

    today_str = datetime.date.today().isoformat()
    cur.execute("SELECT date_sk, full_date FROM dim_date")
    date_rows = cur.fetchall()
    date_sk_today = None
    first_date_sk = None
    for d_sk, f_date in date_rows:
        if first_date_sk is None:
            first_date_sk = d_sk
        if f_date and str(f_date).split()[0] == today_str:
            date_sk_today = d_sk
            break
    if date_sk_today is None:
        date_sk_today = first_date_sk

    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_map = {}
    for p_sk, w, m, l in cur.fetchall():
        platform_map[(bool(w), bool(m), bool(l))] = p_sk

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0
    }

    def parse_bool(val):
        if val is None or pd.isna(val):
            return False
        if isinstance(val, (bool, np.bool_)):
            return bool(val)
        if isinstance(val, (int, float, np.number)):
            return bool(val)
        return str(val).strip().lower() in ('true', '1', 't', 'yes')

    def parse_int(val):
        if val is None or pd.isna(val):
            return None
        try:
            return int(float(val))
        except Exception:
            return None

    def parse_float(val):
        if val is None or pd.isna(val):
            return None
        try:
            return float(val)
        except Exception:
            return None

    def parse_date(val):
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        try:
            return pd.to_datetime(s).strftime('%Y-%m-%d')
        except Exception:
            return None

    def parse_owners(val):
        if val is None or pd.isna(val):
            return None, None
        s = str(val).replace(',', '').strip()
        parts = s.split(' - ')
        if len(parts) == 2:
            try:
                return int(parts[0].strip()), int(parts[1].strip())
            except Exception:
                pass
        return None, None

    def parse_genres(val):
        if val is None or pd.isna(val):
            return []
        if isinstance(val, (list, tuple, np.ndarray)):
            return [str(g).strip() for g in val if g is not None and not (isinstance(g, float) and pd.isna(g)) and str(g).strip()]
        if isinstance(val, str):
            val_str = val.strip()
            if not val_str or val_str.lower() in ('nan', 'none', 'null', '[]'):
                return []
            if val_str.startswith('[') and val_str.endswith(']'):
                try:
                    parsed = ast.literal_eval(val_str)
                    if isinstance(parsed, (list, tuple)):
                        return [str(g).strip() for g in parsed if g and str(g).strip()]
                except Exception:
                    try:
                        parsed = json.loads(val_str.replace("'", '"'))
                        if isinstance(parsed, (list, tuple)):
                            return [str(g).strip() for g in parsed if g and str(g).strip()]
                    except Exception:
                        pass
            return [g.strip() for g in val_str.split(',') if g.strip()]
        return []

    records = df.to_dict('records')

    games_dict = {}
    fact_specs = []
    app_genres_map = {}

    for r in records:
        app_id_raw = r.get('app_id')
        if app_id_raw is None or pd.isna(app_id_raw):
            continue
        app_id = str(app_id_raw).strip()
        if not app_id or app_id.lower() in ('nan', 'none', 'null'):
            continue

        name_raw = r.get('name')
        game_name = str(name_raw).strip() if name_raw is not None and not pd.isna(name_raw) else None

        req_age = parse_int(r.get('required_age'))
        rel_date = parse_date(r.get('release_date'))

        est_owners_raw = r.get('estimated_owners')
        est_owners = str(est_owners_raw).strip() if est_owners_raw is not None and not pd.isna(est_owners_raw) else None
        o_min, o_max = parse_owners(est_owners)

        if app_id not in games_dict:
            games_dict[app_id] = (app_id, game_name, req_age, rel_date, est_owners, o_min, o_max)

        win = parse_bool(r.get('windows'))
        mac = parse_bool(r.get('mac'))
        lin = parse_bool(r.get('linux'))
        platform_sk = platform_map.get((win, mac, lin))

        price_usd = parse_float(r.get('price'))
        discount_pct = parse_int(r.get('discount'))
        peak_ccu = parse_int(r.get('peak_ccu'))
        pos_rev = parse_int(r.get('positive'))
        neg_rev = parse_int(r.get('negative'))
        avg_playtime = parse_int(r.get('average_playtime_forever'))

        fact_specs.append((app_id, platform_sk, price_usd, discount_pct, peak_ccu, pos_rev, neg_rev, avg_playtime))

        genres_list = parse_genres(r.get('genres'))
        if app_id not in app_genres_map:
            app_genres_map[app_id] = set()
        for g in genres_list:
            if g:
                app_genres_map[app_id].add(g)

    cur.execute("SELECT app_id, game_sk FROM dim_game")
    game_sk_map = {str(r[0]): r[1] for r in cur.fetchall()}

    new_games = [data for app_id, data in games_dict.items() if app_id not in game_sk_map]
    if new_games:
        cur.executemany("""
            INSERT INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, new_games)
        counts["dim_game"] = len(new_games)

        cur.execute("SELECT app_id, game_sk FROM dim_game")
        game_sk_map = {str(r[0]): r[1] for r in cur.fetchall()}

    cur.execute("SELECT genre_name, genre_sk FROM dim_genre")
    genre_sk_map = {r[0]: r[1] for r in cur.fetchall()}

    all_genres_in_df = set()
    for g_set in app_genres_map.values():
        all_genres_in_df.update(g_set)

    new_genres = [g for g in all_genres_in_df if g not in genre_sk_map]
    if new_genres:
        cur.executemany("INSERT INTO dim_genre (genre_name) VALUES (?)", [(g,) for g in new_genres])
        counts["dim_genre"] = len(new_genres)

        cur.execute("SELECT genre_name, genre_sk FROM dim_genre")
        genre_sk_map = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("SELECT game_sk, genre_sk FROM bridge_game_genre")
    existing_bridge = set(cur.fetchall())

    new_bridge_tuples = set()
    for app_id, g_set in app_genres_map.items():
        g_sk = game_sk_map.get(app_id)
        if g_sk is None:
            continue
        for g_name in g_set:
            gn_sk = genre_sk_map.get(g_name)
            if gn_sk is not None:
                pair = (g_sk, gn_sk)
                if pair not in existing_bridge:
                    new_bridge_tuples.add(pair)

    if new_bridge_tuples:
        cur.executemany("INSERT INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", list(new_bridge_tuples))
        counts["bridge_game_genre"] = len(new_bridge_tuples)

    fact_rows = []
    for spec in fact_specs:
        app_id = spec[0]
        g_sk = game_sk_map.get(app_id)
        if g_sk is None:
            continue
        fact_rows.append((g_sk, date_sk_today) + spec[1:])

    if fact_rows:
        cur.executemany("""
            INSERT INTO fact_game (game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu, positive_reviews, negative_reviews, average_playtime_mins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, fact_rows)
        counts["fact_game"] = len(fact_rows)

    return counts