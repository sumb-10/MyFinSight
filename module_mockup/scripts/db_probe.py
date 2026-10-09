"""
Read-only probe of the team's news database. Credentials come ONLY from MyFinSight/.env (never from the command line).

.env keys (either a full URL or the parts; ENGINE / PORT / NAME are optional — the script tries PostgreSQL then MySQL):
  NEWS_DB_URL=postgresql://reader:PASSWORD@ENDPOINT:5432/DBNAME?sslmode=require
  -- or --
  NEWS_DB_ENGINE=postgresql        # postgresql | mysql
  NEWS_DB_HOST=xxxx.rds.amazonaws.com
  NEWS_DB_PORT=5432                # 5432 postgres / 3306 mysql
  NEWS_DB_NAME=dbname
  NEWS_DB_USER=reader
  NEWS_DB_PASSWORD=...
  NEWS_DB_SSL=require              # optional

  python scripts/db_probe.py            # connect, list tables, describe news-like tables
  python scripts/db_probe.py --table t  # describe one table (columns, row count, date range, 3 sample rows)
"""
import argparse, os, re, sys, time
from pathlib import Path
from urllib.parse import quote_plus
import llm_config as C

ENV = Path(C.ENV_FILE)


def load_env():
    from common import load_dotenv
    kv = load_dotenv(ENV)
    kv.update({k: v for k, v in os.environ.items() if k.startswith("NEWS_DB_")})
    return kv


def candidate_urls(kv):
    """Yield connection URLs to try. Engine / port / db name may be omitted: we try PostgreSQL then MySQL with sensible defaults."""
    if kv.get("NEWS_DB_URL"):
        url = kv["NEWS_DB_URL"]
        if url.startswith("postgres://"): url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"): url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("mysql://"): url = url.replace("mysql://", "mysql+pymysql://", 1)
        yield url; return
    need = ["NEWS_DB_HOST", "NEWS_DB_USER", "NEWS_DB_PASSWORD"]
    missing = [k for k in need if not kv.get(k)]
    if missing:
        sys.exit(f"[db_probe] .env is missing {missing} (or set NEWS_DB_URL). File: {ENV}")
    user, pw, host = quote_plus(kv["NEWS_DB_USER"]), quote_plus(kv["NEWS_DB_PASSWORD"]), kv["NEWS_DB_HOST"]
    eng = (kv.get("NEWS_DB_ENGINE") or "").lower()
    engines = ["postgresql", "mysql"] if not eng else [("mysql" if eng.startswith("mysql") else "postgresql")]
    for e in engines:
        port = kv.get("NEWS_DB_PORT") or ("3306" if e == "mysql" else "5432")
        names = [kv["NEWS_DB_NAME"]] if kv.get("NEWS_DB_NAME") else (["postgres", "dbmaster"] if e == "postgresql" else [""])
        for name in names:
            if e == "postgresql":
                ssl = kv.get("NEWS_DB_SSL", "require")
                yield f"postgresql+psycopg://{user}:{pw}@{host}:{port}/{name}?sslmode={ssl}"
            else:
                yield f"mysql+pymysql://{user}:{pw}@{host}:{port}/{name}"


def redact(url):
    return re.sub(r"://([^:/]+):([^@]+)@", r"://\1:***@", url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=None)
    ap.add_argument("--limit", type=int, default=3)
    a = ap.parse_args()
    from sqlalchemy import create_engine, inspect, text
    kv = load_env(); last_err = None; eng = None; url = None
    for cand in candidate_urls(kv):
        print("[db_probe] trying", redact(cand), flush=True)
        t0 = time.time()
        try:
            e_ = create_engine(cand, connect_args={"connect_timeout": 10})
            with e_.connect() as con:
                ver = con.execute(text("select version()")).scalar()
            print(f"[db_probe] connected in {time.time() - t0:.1f}s: {str(ver)[:90]}")
            eng, url = e_, cand; break
        except Exception as e:
            last_err = e; print(f"   failed ({time.time() - t0:.1f}s): {type(e).__name__}: {str(e)[:140]}")
    if eng is None:
        msg = str(last_err)
        print(f"[db_probe] FAILED: {type(last_err).__name__}: {msg[:300]}")
        if "timeout" in msg.lower() or "timed out" in msg.lower() or "could not connect" in msg.lower():
            print("  -> 연결 타임아웃: RDS/Lightsail 보안그룹(인바운드 5432/3306)에 이 PC의 공인 IP 허용 여부, 'Public mode' 설정, VPN 필요 여부를 팀원에게 확인하세요.")
        if "password" in msg.lower() or "authentication" in msg.lower() or "access denied" in msg.lower():
            print("  -> 인증 실패: 사용자명/비밀번호/DB 이름 확인. 비밀번호 특수문자는 그대로 넣으면 됩니다.")
        sys.exit(1)
    t0 = time.time()
    try:
        with eng.connect() as con:
            try:
                dbs = con.execute(text("select datname from pg_database where not datistemplate" if "psycopg" in url else "show databases")).scalars().all()
                print("[db_probe] databases:", dbs)
            except Exception as e:
                print("[db_probe] could not list databases:", str(e)[:80])
            insp = inspect(con)
            schemas = [s for s in insp.get_schema_names() if s not in ("information_schema", "pg_catalog", "pg_toast", "mysql", "performance_schema", "sys")]
            tables = []
            for s in schemas:
                for tname in insp.get_table_names(schema=s):
                    tables.append((s, tname))
            print(f"[db_probe] schemas={schemas} tables={len(tables)}")
            for s, tname in tables: print(f"   {s}.{tname}")
            targets = [(s, tn) for s, tn in tables if a.table and tn == a.table] if a.table else [(s, tn) for s, tn in tables if re.search(r"news|article|headline|evidence|doc", tn, re.I)]
            for s, tn in targets:
                print(f"\n== {s}.{tn} ==")
                cols = insp.get_columns(tn, schema=s)
                for c in cols: print(f"   {c['name']:<28} {str(c['type']):<24} {'NULL' if c.get('nullable', True) else 'NOT NULL'}")
                q = f'"{s}"."{tn}"' if "psycopg" in url else f"`{s}`.`{tn}`"
                n = con.execute(text(f"select count(*) from {q}")).scalar(); print(f"   rows: {n:,}")
                dcols = [c["name"] for c in cols if re.search(r"date|time|published|created|_at$", c["name"], re.I)]
                for dc in dcols[:3]:
                    try:
                        lo, hi = con.execute(text(f"select min({dc}), max({dc}) from {q}")).one(); print(f"   {dc}: {lo} .. {hi}")
                    except Exception as e: print(f"   {dc}: range query failed ({str(e)[:60]})")
                tcols = [c["name"] for c in cols if re.search(r"ticker|symbol|company|stock", c["name"], re.I)]
                for tc in tcols[:2]:
                    try:
                        top = con.execute(text(f"select {tc}, count(*) c from {q} group by {tc} order by c desc limit 8")).all(); print(f"   top {tc}: {top}")
                    except Exception as e: print(f"   {tc}: group query failed ({str(e)[:60]})")
                rows = con.execute(text(f"select * from {q} limit {a.limit}")).mappings().all()
                for r in rows: print("   sample:", {k: (str(v)[:70] + "…" if v is not None and len(str(v)) > 70 else v) for k, v in r.items()})
    except Exception as e:
        print(f"[db_probe] inspection FAILED after {time.time() - t0:.1f}s: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
