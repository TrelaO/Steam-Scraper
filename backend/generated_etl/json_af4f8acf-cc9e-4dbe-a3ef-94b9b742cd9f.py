import json
import ast
import datetime
import pandas as pd

def safe_parse(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (int, float, bool)):
        if isinstance(val, float) and pd.isna(val):
            return None
        return val
    if isinstance(val, str):
        val = val.strip()
        if not val or val.lower() in ('nan', 'none', 'null', 'nat'):
            return None
        try:
            return json.loads(val)
        except Exception:
            try:
                return ast.literal_eval(val)
            except Exception:
                return val
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    return val

def to_int(val):
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            if pd.isna(val):
                return None
            return int(val)
        s = str(val).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        return int(float(s))
    except (ValueError, TypeError):
        return None

def to_float(val):
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            if pd.isna(val):
                return None
            return float(val)
        s = str(val).strip()
        if not s or s.lower() in ('nan', 'none', 'null'):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None

def run_etl(df, conn):
    cur = conn.cursor()

    today = datetime.date.today()
    today_str = today.isoformat()
    today_int = int(today.strftime("%Y%m%d"))

    cur.execute("SELECT date_sk, full_date FROM dim_date")
    date_rows = cur.fetchall()
    default_date_sk = None
    if date_rows:
        for d_sk, f_date in date_rows:
            if str(f_date) == today_str or d_sk == today_int or str(f_date).startswith(today_str):
                default_date_sk = d_sk
                break
        if default_date_sk is None:
            default_date_sk = date_rows[0][0]

    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_rows = cur.fetchall()

    def find_platform_sk(win, mac, lin):
        w_bool, m_bool, l_bool = bool(win), bool(mac), bool(lin)
        for row in platform_rows:
            p_sk, p_w, p_m, p_l = row
            if bool(p_w) == w_bool and bool(p_m) == m_bool and bool(p_l) == l_bool:
                return p_sk
        if platform_rows:
            return platform_rows[0][0]
        return None

    cols_lower = [str(c).lower() for c in df.columns]
    is_row_oriented = any(k in cols_lower for k in ['app_id', 'appid', 'game_id', 'id']) and any(k in cols_lower for k in ['game_name', 'name', 'title'])

    records = []
    if is_row_oriented:
        for _, row in df.iterrows():
            rec = {}
            for col in df.columns:
                scol = str(col).lower()
                val = row[col]
                if scol in ['app_id', 'appid', 'id', 'game_id']:
                    rec['app_id'] = str(val) if pd.notna(val) else None
                elif scol in ['game_name', 'name', 'title']:
                    rec['game_name'] = val
                elif 'release' in scol or 'date' in scol:
                    rec['release_date'] = val
                elif 'age' in scol:
                    rec['required_age'] = val
                elif 'price' in scol:
                    rec['price'] = val
                elif 'owner' in scol:
                    rec['owners'] = val
                elif 'platform' in scol:
                    rec['platforms'] = val
                elif 'metric' in scol or 'review' in scol or 'ccu' in scol:
                    rec['metrics'] = val
                elif 'genre' in scol:
                    rec['genres'] = val
            if rec.get('app_id') and str(rec['app_id']).lower() not in ['nan', 'none', 'null', '']:
                records.append(rec)
    else:
        for col in df.columns:
            col_str = str(col).strip()
            if not col_str or col_str.lower() in ['nan', 'none', 'null', '']:
                continue
            
            series = df[col]
            rec = {}
            
            has_index_names = False
            for idx_label in series.index:
                s_idx = str(idx_label).lower()
                if any(k in s_idx for k in ['name', 'title', 'release', 'age', 'price', 'owner', 'platform', 'metric', 'review', 'genre', 'app']):
                    has_index_names = True
                    break
            
            if has_index_names:
                for idx_label, val in series.items():
                    s_idx = str(idx_label).lower()
                    if 'app' in s_idx or 'id' in s_idx:
                        rec['app_id'] = val
                    elif 'name' in s_idx or 'title' in s_idx:
                        rec['game_name'] = val
                    elif 'release' in s_idx or 'date' in s_idx:
                        rec['release_date'] = val
                    elif 'age' in s_idx:
                        rec['required_age'] = val
                    elif 'price' in s_idx:
                        rec['price'] = val
                    elif 'owner' in s_idx:
                        rec['owners'] = val
                    elif 'platform' in s_idx:
                        rec['platforms'] = val
                    elif 'metric' in s_idx or 'review' in s_idx or 'ccu' in s_idx:
                        rec['metrics'] = val
                    elif 'genre' in s_idx:
                        rec['genres'] = val
                if not rec.get('app_id'):
                    rec['app_id'] = col_str
            else:
                rec['app_id'] = col_str
                for val in series.values:
                    parsed = safe_parse(val)
                    if parsed is None:
                        continue
                    if isinstance(parsed, list):
                        rec['genres'] = parsed
                    elif isinstance(parsed, dict):
                        keys = [str(k).lower() for k in parsed.keys()]
                        if any(k in keys for k in ['windows', 'mac', 'linux']):
                            rec['platforms'] = parsed
                        elif any(k in keys for k in ['base_price_usd', 'price_usd', 'current_discount_pct', 'price']):
                            rec['price'] = parsed
                        elif any(k in keys for k in ['min', 'max', 'owners_min', 'owners_max']):
                            rec['owners'] = parsed
                        elif any(k in keys for k in ['peak_concurrent_users', 'reviews_positive', 'reviews_negative', 'avg_playtime_minutes', 'peak_ccu']):
                            rec['metrics'] = parsed
                    else:
                        s_val = str(parsed).strip()
                        if len(s_val) == 10 and s_val.count('-') == 2:
                            rec['release_date'] = s_val
                        elif s_val.isdigit() and int(s_val) <= 120 and 'required_age' not in rec:
                            rec['required_age'] = int(s_val)
                        elif 'game_name' not in rec:
                            rec['game_name'] = s_val

                vals = list(series.values)
                if 'game_name' not in rec and len(vals) > 0: rec['game_name'] = vals[0]
                if 'release_date' not in rec and len(vals) > 1: rec['release_date'] = vals[1]
                if 'required_age' not in rec and len(vals) > 2: rec['required_age'] = vals[2]
                if 'price' not in rec and len(vals) > 3: rec['price'] = vals[3]
                if 'owners' not in rec and len(vals) > 4: rec['owners'] = vals[4]
                if 'platforms' not in rec and len(vals) > 5: rec['platforms'] = vals[5]
                if 'metrics' not in rec and len(vals) > 6: rec['metrics'] = vals[6]
                if 'genres' not in rec and len(vals) > 7: rec['genres'] = vals[7]

            if rec.get('app_id') and str(rec['app_id']).lower() not in ['nan', 'none', 'null', '']:
                records.append(rec)

    counts = {
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0
    }

    for rec in records:
        app_id = rec.get('app_id')
        if not app_id or str(app_id).lower() in ['nan', 'none', 'null', '']:
            continue

        game_name = rec.get('game_name')
        game_name = str(game_name) if (game_name is not None and pd.notna(game_name)) else None

        required_age = to_int(rec.get('required_age'))

        release_date = rec.get('release_date')
        release_date = str(release_date) if (release_date is not None and pd.notna(release_date)) else None

        owners_val = safe_parse(rec.get('owners'))
        owners_min = None
        owners_max = None
        estimated_owners = None
        if isinstance(owners_val, dict):
            owners_min = to_int(owners_val.get('min', owners_val.get('owners_min')))
            owners_max = to_int(owners_val.get('max', owners_val.get('owners_max')))
            if owners_min is not None and owners_max is not None:
                estimated_owners = f"{owners_min} - {owners_max}"
            elif owners_min is not None:
                estimated_owners = f"{owners_min}+"
        elif isinstance(owners_val, str):
            estimated_owners = owners_val

        price_val = safe_parse(rec.get('price'))
        price_usd = None
        discount_pct = None
        if isinstance(price_val, dict):
            price_usd = to_float(price_val.get('base_price_usd', price_val.get('price_usd', price_val.get('price'))))
            discount_pct = to_int(price_val.get('current_discount_pct', price_val.get('discount_pct', price_val.get('discount'))))
        elif isinstance(price_val, (int, float)):
            price_usd = to_float(price_val)

        platforms_val = safe_parse(rec.get('platforms'))
        win, mac, lin = False, False, False
        if isinstance(platforms_val, dict):
            win = bool(platforms_val.get('windows', False))
            mac = bool(platforms_val.get('mac', False))
            lin = bool(platforms_val.get('linux', False))

        platform_sk = find_platform_sk(win, mac, lin)

        metrics_val = safe_parse(rec.get('metrics'))
        peak_ccu = None
        pos_reviews = None
        neg_reviews = None
        avg_playtime = None
        if isinstance(metrics_val, dict):
            peak_ccu = to_int(metrics_val.get('peak_concurrent_users', metrics_val.get('peak_ccu')))
            pos_reviews = to_int(metrics_val.get('reviews_positive', metrics_val.get('positive_reviews')))
            neg_reviews = to_int(metrics_val.get('reviews_negative', metrics_val.get('negative_reviews')))
            avg_playtime = to_int(metrics_val.get('avg_playtime_minutes', metrics_val.get('average_playtime_mins')))

        cur.execute("""
            INSERT OR IGNORE INTO dim_game (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max))
        if cur.rowcount > 0:
            counts["dim_game"] += 1

        cur.execute("""
            UPDATE dim_game SET
                game_name = COALESCE(?, game_name),
                required_age = COALESCE(?, required_age),
                release_date = COALESCE(?, release_date),
                estimated_owners = COALESCE(?, estimated_owners),
                owners_min = COALESCE(?, owners_min),
                owners_max = COALESCE(?, owners_max)
            WHERE app_id = ?
        """, (game_name, required_age, release_date, estimated_owners, owners_min, owners_max, app_id))

        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        game_sk = cur.fetchone()[0]

        genres_raw = safe_parse(rec.get('genres'))
        genre_list = []
        if isinstance(genres_raw, list):
            genre_list = [str(g).strip() for g in genres_raw if g]
        elif isinstance(genres_raw, str):
            s = genres_raw.strip("[]'\" ")
            genre_list = [g.strip(" '\"") for g in s.split(',') if g.strip(" '\"")]

        for g_name in genre_list:
            if not g_name or not isinstance(g_name, str):
                continue
            g_name = g_name.strip()
            if not g_name:
                continue

            cur.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", (g_name,))
            if cur.rowcount > 0:
                counts["dim_genre"] += 1

            cur.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (g_name,))
            g_row = cur.fetchone()
            if g_row:
                genre_sk = g_row[0]
                cur.execute("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, genre_sk))
                if cur.rowcount > 0:
                    counts["bridge_game_genre"] += 1

        cur.execute("""
            INSERT INTO fact_game (
                game_sk, date_sk, platform_sk, price_usd, discount_pct,
                peak_ccu, positive_reviews, negative_reviews, average_playtime_mins
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_sk, default_date_sk, platform_sk, price_usd, discount_pct, peak_ccu, pos_reviews, neg_reviews, avg_playtime))
        if cur.rowcount > 0:
            counts["fact_game"] += 1

    return counts