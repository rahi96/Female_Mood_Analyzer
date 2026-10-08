"""Verify the TTC rewrite works for MULTIPLE users (not just user 17)."""
import json
import subprocess
import time
import pymysql
from pymysql.cursors import DictCursor

# 1) Pick several real users from the DB
conn = pymysql.connect(
    host='mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com',
    port=3306, user='pulse', password='Pul$e2026_mysql',
    database='pulse_mysql', cursorclass=DictCursor,
)
cursor = conn.cursor()
cursor.execute("""
    SELECT u.id, u.full_name,
           (SELECT COUNT(*) FROM menstrual_cycles WHERE user_id = u.id) AS cycles,
           (SELECT COUNT(*) FROM opk_logs ol JOIN menstrual_cycles mc ON ol.cycle_id = mc.id WHERE mc.user_id = u.id) AS opks,
           (SELECT COUNT(*) FROM bbt_logs WHERE user_id = u.id) AS bbts
    FROM users u
    WHERE u.status = 'active'
    ORDER BY u.id
    LIMIT 25
""")
users = cursor.fetchall()
conn.close()

# 2) Hit the TTC endpoint for each one, time it, show key fields
print("\n" + "=" * 110)
print("MULTI-USER TTC VERIFICATION  — proves the service handles any user, not just #17")
print("=" * 110)
print(f"\n{'uid':<5} {'name':<22} {'cycles':<7} {'opks':<5} {'bbts':<5} {'ms':<7} {'status':<13} {'cycle_day':<10} {'phase':<20} {'ai_cached'}")
print("-" * 110)

for u in users:
    uid = u['id']
    name = (u.get('full_name') or 'N/A')[:21]
    url = f"http://localhost:8000/api/trying-to-conceive?user_id={uid}"

    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            ["curl.exe", "-s", "--max-time", "30", url],
            capture_output=True, text=True, timeout=35,
        )
        ms = (time.perf_counter() - t0) * 1000
        body = result.stdout
    except Exception as e:
        print(f"{uid:<5} {name:<22} {u['cycles']:<7} {u['opks']:<5} {u['bbts']:<5} ERROR: {e}")
        continue

    try:
        data = json.loads(body)
    except Exception:
        print(f"{uid:<5} {name:<22} {u['cycles']:<7} {u['opks']:<5} {u['bbts']:<5} {ms:<7.0f} BAD JSON")
        continue

    status = data.get('status', '?')
    if status == 'empty':
        print(f"{uid:<5} {name:<22} {u['cycles']:<7} {u['opks']:<5} {u['bbts']:<5} {ms:<7.0f} {'empty':<13} {'-':<10} {'-':<20} -")
        continue

    ttc = data.get('trying_to_conceive') or {}
    cc = ttc.get('cycle_context') or {}
    lh = ttc.get('lh_surge') or {}
    cycle_day = str(cc.get('cycle_day', '?'))
    phase = (cc.get('phase', '?'))[:19]
    lh_status = (lh.get('status', '?'))
    cached = ttc.get('ai_cached', '?')
    print(f"{uid:<5} {name:<22} {u['cycles']:<7} {u['opks']:<5} {u['bbts']:<5} {ms:<7.0f} {lh_status:<13} {cycle_day:<10} {phase:<20} {cached}")

print()
