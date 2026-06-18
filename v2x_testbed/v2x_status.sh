#!/usr/bin/env bash
# v2x_status — print a compact health summary of the V2X testbed
# Run on the laptop (where the Desktop server and its SQLite database live).
# Output can be copy-pasted to share for diagnosis.
#
# Usage:
#   ~/V2X/v2x_testbed/v2x_status.sh
#   ~/V2X/v2x_testbed/v2x_status.sh > ~/v2x_status.txt

TESTBED="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DB="$TESTBED/desktop/database/v2x_testbed.db"

python3 - "$DB" << 'PYEOF'
import sys, os, sqlite3
from datetime import datetime

db_path = sys.argv[1]
if not os.path.exists(db_path):
    print("ERROR: database not found — is v2x_run_desktop running?")
    print(f"  Expected: {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

W = 62
print("=" * W)
print(f"  V2X STATUS — {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
print("=" * W)

# --- Entities ---
entities = conn.execute(
    "SELECT entity_id, entity_type, is_emergency, status, registered_at FROM entities ORDER BY entity_id"
).fetchall()
print(f"\nENTITIES ({len(entities)} registered):")
if entities:
    for e in entities:
        em = " EMERG" if e["is_emergency"] else "      "
        ts = e["registered_at"][:19] if e["registered_at"] else "?"
        print(f"  {e['entity_id']:<22} {e['entity_type']:<8}{em}  {e['status']:<12}  reg:{ts}")
else:
    print("  (none)")

# --- Event counts by type ---
all_counts = {r["event_type"]: r["n"] for r in conn.execute(
    "SELECT event_type, COUNT(*) as n FROM auth_events GROUP BY event_type"
).fetchall()}

ok_events = [
    "AUTH_REQUEST_RECEIVED",
    "SESSION_ESTABLISHED",
    "KC1_VERIFY_PASS",
    "EMERGENCY_PRIORITY_GRANTED",
]
fail_events = [
    "POST_AUTH_HMAC_FAIL",
    "POST_AUTH_DECRYPT_FAIL",
    "KC1_VERIFY_FAIL",
    "SIGNATURE_CHECK_FAIL",
    "TIMESTAMP_CHECK_FAIL",
    "REPLAY_DETECTED",
]

print("\nEVENT COUNTS:")
for t in ok_events:
    n = all_counts.get(t, 0)
    if n:
        print(f"  OK   {t:<38}  {n}")
for t in fail_events:
    n = all_counts.get(t, 0)
    if n:
        print(f"  FAIL {t:<38}  {n}")
other = {k: v for k, v in all_counts.items() if k not in ok_events and k not in fail_events}
for t, n in sorted(other.items()):
    print(f"       {t:<38}  {n}")

total_fail = sum(all_counts.get(t, 0) for t in fail_events)
if total_fail == 0:
    print("  --> No failures ✓")
else:
    print(f"  --> TOTAL FAILURES: {total_fail}")

# --- Recent errors ---
errors = conn.execute(
    """SELECT timestamp, event_type, source_entity, session_id_hex
       FROM auth_events
       WHERE event_type IN ('POST_AUTH_HMAC_FAIL','KC1_VERIFY_FAIL',
             'POST_AUTH_DECRYPT_FAIL','REPLAY_DETECTED',
             'SIGNATURE_CHECK_FAIL','TIMESTAMP_CHECK_FAIL')
       ORDER BY event_id DESC LIMIT 8"""
).fetchall()
if errors:
    print(f"\nRECENT ERRORS (last {len(errors)}):")
    for e in errors:
        ts = e["timestamp"][:19] if e["timestamp"] else "?"
        sid = (e["session_id_hex"] or "")[:8]
        print(f"  {ts}  {e['event_type']:<30}  src:{e['source_entity'] or '?':<16}  sid:{sid}")
else:
    print("\nRECENT ERRORS: none ✓")

# --- Session latency ---
row = conn.execute(
    """SELECT COUNT(*), AVG(end_to_end_latency_ms),
              MIN(end_to_end_latency_ms), MAX(end_to_end_latency_ms)
       FROM session_metrics WHERE auth_result = 'SUCCESS'"""
).fetchone()
if row and row[0]:
    print(f"\nSESSION LATENCY (n={row[0]}):")
    print(f"  avg={row[1]:.1f}ms   min={row[2]:.1f}ms   max={row[3]:.1f}ms")

# --- Emergency grants ---
em_count = all_counts.get("EMERGENCY_PRIORITY_GRANTED", 0)
print(f"\nEMERGENCY PRIORITY GRANTS: {em_count}")

conn.close()
print("\n" + "=" * W)
PYEOF
