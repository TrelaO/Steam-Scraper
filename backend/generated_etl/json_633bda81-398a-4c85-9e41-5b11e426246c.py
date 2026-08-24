import ast
import json
import re
import pandas as pd

def safe_parse(v):
    if isinstance(v, (dict, list)):
        return v
    if pd.isna(v) or v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
            try:
                return ast.literal_eval(s)
            except Exception:
                pass
            s_json = s.replace("'", '"')
            s_json = re.sub(r'\bTrue\b', 'true', s_json)
            s_json = re.sub(r'\bFalse\b', 'false', s_json)
            s_json = re.sub(r'\bNone\b', 'null', s_json)
            try:
                return json.loads(s_json)
            except Exception:
                pass
    return v

def run_etl(df, conn):
    cur = conn.cursor()
    
    counts = {
        "dim_date": 0,
        "dim_platform": 0,
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0
    }
    
    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = DATE('now') OR full_date = strftime('%Y-%m-%d', 'now')")
    row = cur.fetchone()
    if row:
        today_date_sk = row[0]
    else:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY ABS(JULIANDAY(full_date) - JULIANDAY('now')) LIMIT 1")
        row = cur.fetchone()
        if row:
            today_date_sk = row[0]
        else:
            cur.execute("SELECT date_sk FROM dim_date ORDER BY date_sk DESC LIMIT 1")
            row = cur.fetchone()
            today_date_sk = row[0] if row else None

    records = []
    col_names_lower = [str(c).lower() for c in df.columns]
    
    has_row_headers = any(k in col_names_lower for k in ['app_id', 'appid', 'game_name'])
    if has_row_headers and len(df) > 1 and not all(str(c).isdigit() for c in df.columns[:3]):
        for _, r in df.iterrows():
            rec = {str(k).lower(): v for k, v in r.to_dict().items()}
            records.append(rec)
    else:
        positional_keys = ['name', 'release_date', 'required_age', 'pricing', 'owners', 'platforms', 'metrics', 'genres']
        for col in df.columns:
            app_id = str(col).strip()
            rec = {'app_id': app_id}
            col_series = df[col]
            for idx_val, val in col_series.items():
                idx_str = str(idx_val).lower().strip()
                if isinstance(idx_val, int) and idx_val < len(positional_keys):
                    key = positional_keys[idx_val]
                elif idx_str.isdigit() and int(idx_str) < len(positional_keys):
                    key = positional_keys[int(idx_str)]
                else:
                    key = idx_str
                rec[key] = val
            records.append(rec)

    for rec in records:
        app_id_val = rec.get('app_id') or rec.get('appid') or rec.get('id')
        if app_id_val is None or pd.isna(app_id_val):
            continue
        app_id = str(app_id_val).strip()
        if not app_id or app_id.lower() in ('nan', 'none', 'null'):
            continue

        game_name = str(rec.get('game_name') or rec.get('name') or '').strip()

        req_age = rec.get('required_age')
        try:
            required_age = int(req_age) if req_age is not None and not pd.isna(req_age) else 0
        except Exception:
            required_age = 0

        rel_date = rec.get('release_date')
        release_date = str(rel_date).strip() if rel_date is not None and not pd.isna(rel_date) else None

        owners_raw = rec.get('owners')
        owners_parsed = safe_parse(owners_raw)
        if isinstance(owners_parsed, dict):
            try:
                owners_min = int(owners_parsed.get('min', 0))
            except Exception:
                owners_min = 0
            try:
                owners_max = int(owners_parsed.get('max', 0))
            except Exception:
                owners_max = 0
            estimated_owners = f"{owners_min} - {owners_max}"
        else:
            try:
                owners_min = int(rec.get('owners_min', 0))
            except Exception:
                owners_min = 0
            try:
                owners_max = int(rec.get('owners_max', 0))
            except Exception:
                owners_max = 0
            estimated_owners = str(rec.get('estimated_owners', '') or f"{owners_min} - {owners_max}")

        pricing_raw = rec.get('pricing')
        pricing_parsed = safe_parse(pricing_raw)
        if isinstance(pricing_parsed, dict):
            try:
                price_usd = float(pricing_parsed.get('base_price_usd', 0.0))
            except Exception:
                price_usd = 0.0
            try:
                discount_pct = int(pricing_parsed.get('current_discount_pct', 0))
            except Exception:
                discount_pct = 0
        else:
            try:
                price_usd = float(rec.get('price_usd', 0.0))
            except Exception:
                price_usd = 0.0
            try:
                discount_pct = int(rec.get('discount_pct', 0))
            except Exception:
                discount_pct = 0

        plat_raw = rec.get('platforms')
        plat_parsed = safe_parse(plat_raw)
        if isinstance(plat_parsed, dict):
            supports_win = bool(plat_parsed.get('windows', False))
            supports_mac = bool(plat_parsed.get('mac', False))
            supports_linux = bool(plat_parsed.get('linux', False))
        else:
            supports_win = bool(rec.get('supports_windows', False))
            supports_mac = bool(rec.get('supports_mac', False))
            supports_linux = bool(rec.get('supports_linux', False))

        metrics_raw = rec.get('metrics')
        metrics_parsed = safe_parse(metrics_raw)
        if isinstance(metrics_parsed, dict):
            try:
                peak_ccu = int(metrics_parsed.get('peak_concurrent_users', 0))
            except Exception:
                peak_ccu = 0
            try:
                pos_reviews = int(metrics_parsed.get('reviews_positive', 0))
            except Exception:
                pos_reviews = 0
            try:
                neg_reviews = int(metrics_parsed.get('reviews_negative', 0))
            except Exception:
                neg_reviews = 0
            try:
                avg_playtime = int(metrics_parsed.get('avg_playtime_minutes', 0))
            except Exception:
                avg_playtime = 0
        else:
            try:
                peak_ccu = int(rec.get('peak_ccu', 0))
            except Exception:
                peak_ccu = 0
            try:
                pos_reviews = int(rec.get('positive_reviews', 0))
            except Exception:
                pos_reviews = 0
            try:
                neg_reviews = int(rec.get('negative_reviews', 0))
            except Exception:
                neg_reviews = 0
            try:
                avg_playtime = int(rec.get('average_playtime_mins', 0))
            except Exception:
                avg_playtime = 0

        genres_raw = rec.get('genres')
        genres_parsed = safe_parse(genres_raw)
        if isinstance(genres_parsed, list):
            genre_list = [str(g).strip() for g in genres_parsed if str(g).strip()]
        elif isinstance(genres_parsed, str):
            genre_list = [g.strip() for g in genres_parsed.split(',') if g.strip()]
        else:
            genre_list = []

        cur.execute(
            """
            INSERT OR IGNORE INTO dim_game (
                app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max)
        )
        if cur.rowcount > 0:
            counts["dim_game"] += cur.rowcount

        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        g_row = cur.fetchone()
        if not g_row:
            continue
        game_sk = g_row[0]

        for gname in genre_list:
            cur.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", (gname,))
            if cur.rowcount > 0:
                counts["dim_genre"] += cur.rowcount

            cur.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (gname,))
            gn_row = cur.fetchone()
            if gn_row:
                genre_sk = gn_row[0]
                cur.execute(
                    "INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)",
                    (game_sk, genre_sk)
                )
                if cur.rowcount > 0:
                    counts["bridge_game_genre"] += cur.rowcount

        cur.execute(
            "SELECT platform_sk FROM dim_platform WHERE supports_windows = ? AND supports_mac = ? AND supports_linux = ?",
            (1 if supports_win else 0, 1 if supports_mac else 0, 1 if supports_linux else 0)
        )
        p_row = cur.fetchone()
        if p_row:
            platform_sk = p_row[0]
        else:
            cur.execute("SELECT platform_sk FROM dim_platform LIMIT 1")
            p_row = cur.fetchone()
            platform_sk = p_row[0] if p_row else None

        cur.execute(
            """
            INSERT INTO fact_game (
                game_sk, date_sk, platform_sk, price_usd, discount_pct, peak_ccu,
                positive_reviews, negative_reviews, average_playtime_mins
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (game_sk, today_date_sk, platform_sk, price_usd, discount_pct, peak_ccu, pos_reviews, neg_reviews, avg_playtime)
        )
        if cur.rowcount > 0:
            counts["fact_game"] += cur.rowcount

    return counts