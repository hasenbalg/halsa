import json
import collections

d = json.load(open("/tmp/bandit-halsa.json"))
print("total issues:", len(d["results"]))
seen = set()
for r in sorted(d["results"], key=lambda r: r["issue_severity"]):
    key = (r["test_id"], r["filename"], r["line_number"])
    if key in seen:
        continue
    seen.add(key)
    loc = r["filename"].split("/")[-1] + ":" + str(r["line_number"])
    print(f"{r['issue_severity']:8s} {r['test_id']} {loc:32s} {r['issue_text'][:80]}")
