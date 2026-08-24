from datetime import date
import pandas as pd

def parse_bool(val):
    if pd.isna(val):
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "t")

def parse_int(val):
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except Exception:
        return None

def parse_float(val):
    if pd.isna(val):
        return None
    try:
        return float(val)
    except Exception:
        return None

def run_etl(df, conn):
    counts = {
        "dim_date": 0,
        "dim_platform": 0,
        "dim_game": 0,
        "dim_genre": 0,
        "bridge_game_genre": 0,
        "fact_game": 0
    }
    
    cur = conn.cursor()
    
    today_str = date.today().isoformat()
    cur.execute("SELECT date_sk FROM dim_date WHERE full_date = ?", (today_str,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT date_sk FROM dim_date ORDER BY full_date DESC LIMIT 1")
        row = cur.fetchone()
    date_sk = row[0] if row else None
    
    cur.execute("SELECT platform_sk, supports_windows, supports_mac, supports_linux FROM dim_platform")
    platform_rows = cur.fetchall()
    platform_map = {}
    for p_sk, w, m, l in platform_rows:
        key = (bool(w), bool(m), bool(l))
        platform_map[key] = p_sk
        
    genre_cache = {}
    
    for _, row in df.iterrows():
        app_id_raw = row.get("AppID") if "AppID" in row else row.get("app_id") if "app_id" in row else None
        if pd.isna(app_id_raw):
            continue
        app_id = str(app_id_raw).strip()
        if not app_id or app_id.lower() == "nan":
            continue
            
        game_name = row.get("Name") if "Name" in row else row.get("game_name")
        game_name = str(game_name) if pd.notna(game_name) and game_name is not None else None
        
        req_age = parse_int(row.get("Required age") if "Required age" in row else row.get("required_age"))
        
        rel_date_raw = row.get("Release date") if "Release date" in row else row.get("release_date")
        rel_date = None
        if pd.notna(rel_date_raw):
            try:
                rel_date = pd.to_datetime(rel_date_raw).strftime("%Y-%m-%d")
            except Exception:
                rel_date = str(rel_date_raw)
                
        est_owners = row.get("Estimated owners") if "Estimated owners" in row else row.get("estimated_owners")
        est_owners = str(est_owners) if pd.notna(est_owners) else None
        
        owners_min = parse_int(row.get("owners_min") if "owners_min" in row else None)
        owners_max = parse_int(row.get("owners_max") if "owners_max" in row else None)
        
        cur.execute("""
            INSERT OR IGNORE INTO dim_game (
                app_id, game_name, required_age, release_date, estimated_owners, owners_min, owners_max
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (app_id, game_name, req_age, rel_date, est_owners, owners_min, owners_max))
        if cur.rowcount > 0:
            counts["dim_game"] += cur.rowcount
            
        cur.execute("SELECT game_sk FROM dim_game WHERE app_id = ?", (app_id,))
        game_sk_row = cur.fetchone()
        if not game_sk_row:
            continue
        game_sk = game_sk_row[0]
        
        win = parse_bool(row.get("Windows") if "Windows" in row else row.get("supports_windows"))
        mac = parse_bool(row.get("Mac") if "Mac" in row else row.get("supports_mac"))
        lin = parse_bool(row.get("Linux") if "Linux" in row else row.get("supports_linux"))
        platform_sk = platform_map.get((win, mac, lin))
        
        genres_raw = row.get("Genres") if "Genres" in row else row.get("genres") if "genres" in row else None
        genre_sks = []
        if pd.notna(genres_raw):
            genre_list = [g.strip() for g in str(genres_raw).split(",") if g.strip()]
            for gname in genre_list:
                if gname not in genre_cache:
                    cur.execute("INSERT OR IGNORE INTO dim_genre (genre_name) VALUES (?)", (gname,))
                    if cur.rowcount > 0:
                        counts["dim_genre"] += cur.rowcount
                    cur.execute("SELECT genre_sk FROM dim_genre WHERE genre_name = ?", (gname,))
                    g_row = cur.fetchone()
                    if g_row:
                        genre_cache[gname] = g_row[0]
                if gname in genre_cache:
                    genre_sks.append(genre_cache[gname])
                    
        for g_sk in genre_sks:
            cur.execute("INSERT OR IGNORE INTO bridge_game_genre (game_sk, genre_sk) VALUES (?, ?)", (game_sk, g_sk))
            if cur.rowcount > 0:
                counts["bridge_game_genre"] += cur.rowcount
                
        price = parse_float(row.get("Price") if "Price" in row else row.get("price_usd"))
        discount = parse_int(row.get("Discount") if "Discount" in row else row.get("discount_pct"))
        peak_ccu = parse_int(row.get("Peak CCU") if "Peak CCU" in row else row.get("peak_ccu"))
        pos_reviews = parse_int(row.get("Positive") if "Positive" in row else row.get("positive_reviews"))
        neg_reviews = parse_int(row.get("Negative") if "Negative" in row else row.get("negative_reviews"))
        playtime = parse_int(row.get("Average playtime forever") if "Average playtime forever" in row else row.get("average_playtime_mins"))
        
        cur.execute("""
            INSERT INTO fact_game (
                game_sk, date_sk, platform_sk, price_usd, discount_pct,
                peak_ccu, positive_reviews, negative_reviews, average_playtime_mins
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_sk, date_sk, platform_sk, price, discount, peak_ccu, pos_reviews, neg_reviews, playtime))
        if cur.rowcount > 0:
            counts["fact_game"] += cur.rowcount

    return counts