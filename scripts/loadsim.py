"""Hälsa load simulation.

Runs INSIDE the load web container (code baked at /app), against the
halsaload database and gunicorn on localhost:8000.

Phases (argv[1]):
  seed  --users N      create N users + 5 years of realistic readings
  pages --users N      HTTP page-load timings (p50/p95) for N users
  queries --users N    in-process query counts/timings per page
  week  --users N      simulate one full week of usage for N users
  stats                db size + per-table sizes + row counts

Results append as JSON lines to /tmp/loadsim-results.jsonl
"""

import argparse
import http.cookiejar
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "halsa.settings")
sys.path.insert(0, "/app")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402

from tracker.models import (  # noqa: E402
    BloodPressureReading, GlucoseReading, Metric, Schedule, WeightReading)

SIMPASS = "load" + "-sim-2026!"
BASE = "http://localhost:8000"
RESULTS = "/tmp/loadsim-results.jsonl"
DAYS = 5 * 365
CSRF_RE = re.compile(
    'name="csrfmiddlewaretoken" value="([^"]+)"')


def out(obj):
    obj["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps(obj, default=str))
    with open(RESULTS, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def pct(values, p):
    if not values:
        return None
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round(p / 100 * (len(vs) - 1)))))
    return round(vs[k], 1)


def summary(label, times, **extra):
    d = {"phase": label, "n": len(times),
         "p50_ms": pct(times, 50), "p95_ms": pct(times, 95),
         "max_ms": round(max(times), 1) if times else None,
         "errors": extra.get("errors", 0)}
    d.update({k: v for k, v in extra.items() if k != "errors"})
    out(d)


# --- seeding ---------------------------------------------------------------

def seed_user(i):
    U = get_user_model()
    username = f"u{i:04d}"
    user, made = U.objects.get_or_create(
        username=username, defaults={"email": f"{username}@load.local"})
    user.set_password(SIMPASS)
    user.save()
    if GlucoseReading.objects.filter(user=user).exists():
        return username, 0
    now = timezone.now()
    start = now - timedelta(days=DAYS)
    g, w, b = [], [], []
    rnd = random.Random(1000 + i)
    base_glu = rnd.uniform(5.4, 6.4)
    base_wt = rnd.uniform(74, 92)
    base_sys = rnd.uniform(115, 132)
    for day in range(DAYS):
        dt0 = start + timedelta(days=day)
        frac = day / DAYS
        # glucose: 4/day, slow upward drift, occasional spikes
        for meal in range(4):
            v = base_glu + 0.6 * frac + rnd.gauss(0, 0.7)
            if rnd.random() < 0.06:
                v += rnd.uniform(2.5, 5.0)
            g.append(GlucoseReading(
                user=user, taken_at=dt0 + timedelta(hours=7 + 4 * meal,
                                                     minutes=rnd.randint(0, 40)),
                value_mmol=Decimal(max(2.8, min(v, 22.0)))))
        # weight: 1/day, slow decline
        w.append(WeightReading(
            user=user, date=(dt0).date(),
            value_kg=Decimal(max(45.0, base_wt - 4.0 * frac
                                 + rnd.gauss(0, 0.25)))))
        # bp: 2/day, slow rise
        for meal in range(2):
            sysb = int(base_sys + 8 * frac + rnd.gauss(0, 5))
            dia = int(76 + 4 * frac + rnd.gauss(0, 4))
            b.append(BloodPressureReading(
                user=user, taken_at=dt0 + timedelta(hours=8 + 12 * meal,
                                                     minutes=rnd.randint(0, 40)),
                systolic=sysb, diastolic=dia,
                pulse=rnd.randint(55, 85) if rnd.random() < 0.7 else None))
    GlucoseReading.objects.bulk_create(g, batch_size=2000)
    WeightReading.objects.bulk_create(w, batch_size=2000)
    BloodPressureReading.objects.bulk_create(b, batch_size=2000)
    for metric, hh, mm in ((Metric.GLUCOSE, 7, 30), (Metric.WEIGHT, 7, 0),
                           (Metric.BP, 20, 0)):
        Schedule.objects.get_or_create(
            user=user, name=f"{metric} sim",
            defaults={"metric": metric, "time": f"{hh:02d}:{mm:02d}",
                      "weekdays": [0, 1, 2, 3, 4, 5, 6]})
    return username, len(g) + len(w) + len(b)


def phase_seed(users):
    t0 = time.time()
    total = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _, n in pool.map(seed_user, range(1, users + 1)):
            total += n
    dt = time.time() - t0
    out({"phase": "seed", "users": users, "rows": total,
         "seconds": round(dt, 1),
         "rows_per_sec": int(total / dt) if dt else None})


# --- HTTP simulation ---------------------------------------------------------

def opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def http_get(op, path):
    t0 = time.perf_counter()
    r = op.open(BASE + path, timeout=60)
    body = r.read()
    return (time.perf_counter() - t0) * 1000, body


def http_login(op, username):
    _, body = http_get(op, "/accounts/login/")
    tok = CSRF_RE.search(body.decode()).group(1)
    data = urllib.parse.urlencode({
        "csrfmiddlewaretoken": tok, "username": username,
        "password": SIMPASS, "next": "/"}).encode()
    req = urllib.request.Request(
        BASE + "/accounts/login/", data=data,
        headers={"Referer": BASE + "/accounts/login/"})
    t0 = time.perf_counter()
    op.open(req, timeout=60).read()
    return (time.perf_counter() - t0) * 1000


def http_post_add(op, glucose):
    _, body = http_get(op, "/add/")
    tok = CSRF_RE.search(body.decode()).group(1)
    from django.utils import timezone as tz
    data = urllib.parse.urlencode({
        "csrfmiddlewaretoken": tok,
        "taken_at": tz.localtime().strftime("%Y-%m-%dT%H:%M"),
        "glucose": f"{glucose:.1f}", "weight": "", "systolic": "",
        "diastolic": "", "pulse": "", "note": ""}).encode()
    req = urllib.request.Request(
        BASE + "/add/", data=data, headers={"Referer": BASE + "/add/"})
    t0 = time.perf_counter()
    op.open(req, timeout=60).read()
    return (time.perf_counter() - t0) * 1000


PAGES = ["/", "/glucose/", "/weight/", "/pressure/", "/history/",
         "/export/pdf/?range=30", "/export/json/"]


def user_walk(i, pages=PAGES, add=False):
    """One user session; returns {path: ms}."""
    op = opener()
    times = {}
    try:
        times["login"] = http_login(op, f"u{i:04d}")
        for p in pages:
            times[p] = http_get(op, p)[0]
        if add:
            times["POST /add/"] = http_post_add(op, 5.0 + (i % 30) / 10)
    except Exception as e:  # noqa: BLE001
        times["error"] = str(e)
    return times


def phase_pages(users, workers=8):
    idxs = random.Random(7).sample(range(1, users + 1), min(users, 40))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        walks = list(pool.map(lambda i: user_walk(i), idxs))
    errors = sum(1 for w in walks if "error" in w)
    keys = ["login"] + PAGES
    for k in keys:
        summary(f"pages[{users}u] {k}",
                [w[k] for w in walks if k in w],
                errors=errors, users=users)
    if errors:
        out({"phase": "pages-errors", "sample": [
            w.get("error") for w in walks if "error" in w][:3]})


def phase_week(users):
    """7 simulated days: each user logs in, adds readings, views pages."""
    t0 = time.time()
    errors = 0
    reqs = 0
    all_add = []
    for day in range(7):
        def day_walk(i, day=day):
            op = opener()
            t = {}
            try:
                t["login"] = http_login(op, f"u{i:04d}")
                for n in range(3):  # 3 glucose adds per day
                    t[f"add{n}"] = http_post_add(op, 5.0 + (i % 20) / 10)
                for p in ("/", "/glucose/", "/history/"):
                    t["get"] = http_get(op, p)[0]
            except Exception as e:  # noqa: BLE001
                t["error"] = str(e)
            return t
        idxs = random.Random(100 + day).sample(
            range(1, users + 1), min(users, 40))
        with ThreadPoolExecutor(max_workers=8) as pool:
            walks = list(pool.map(day_walk, idxs))
        errors += sum(1 for w in walks if "error" in w)
        reqs += len(idxs) * 7
        all_add += [t["add0"] for t in walks if "add0" in t]
    dt = time.time() - t0
    out({"phase": f"week[{users}u]", "seconds": round(dt, 1),
         "requests": reqs, "req_per_sec": round(reqs / dt, 1),
         "errors": errors, "post_add_p50_ms": pct(all_add, 50),
         "post_add_p95_ms": pct(all_add, 95)})


# --- in-process query analysis ----------------------------------------------

def phase_queries(users):
    i = random.Random(3).randint(1, users)
    c = Client(SERVER_NAME="localhost")
    c.login(username=f"u{i:04d}", password=SIMPASS)
    for path in ("/", "/glucose/", "/history/", "/export/json/"):
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            r = c.get(path)
            wall = (time.perf_counter() - t0) * 1000
        db_ms = sum(float(q["time"]) for q in ctx.captured_queries) * 1000
        out({"phase": "queries", "path": path, "status": r.status_code,
             "queries": len(ctx.captured_queries),
             "db_ms": round(db_ms, 1), "wall_ms": round(wall, 1)})


def phase_stats():
    with connection.cursor() as cur:
        cur.execute("SELECT pg_size_pretty(pg_database_size("
                    "current_database())), pg_database_size("
                    "current_database())")
        pretty, raw = cur.fetchone()
        cur.execute(
            "SELECT relname, n_live_tup, "
            "pg_size_pretty(pg_total_relation_size(relid)) "
            "FROM pg_stat_user_tables ORDER BY "
            "pg_total_relation_size(relid) DESC LIMIT 8")
        tables = [list(r) for r in cur.fetchall()]
    out({"phase": "stats", "db_size": pretty, "db_bytes": raw,
         "tables": tables})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase")
    ap.add_argument("--users", type=int, default=10)
    a = ap.parse_args()
    {"seed": phase_seed, "pages": phase_pages, "week": phase_week,
     "queries": phase_queries, "stats": phase_stats}[a.phase](a.users) \
        if a.phase != "stats" else phase_stats()


if __name__ == "__main__":
    main()
