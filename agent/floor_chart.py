"""Chart net rupees against the confidence floor.

The floor is a blunt override of the EV rule: refuse below p(win) = f whatever
the amount at stake. It should HURT at high values, because it starts declining
the high-amount low-probability cases that expected value says are worth an
attempt. Where it stops helping and starts hurting is the answer.
"""
import glob, json, os, re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))

rows = []
for path in glob.glob(os.path.join(HERE, "..", "data", "floor_*.json")):
    f = float(re.search(r"floor_([\d.]+)\.json", path).group(1))
    with open(path, encoding="utf-8") as fh:
        rows.append((f, json.load(fh)))
rows.sort()


def dig(d):
    """Pull the agent's net_rupees out, whatever shape the scorer wrote.

    Handles: a list of policy records, a dict keyed by policy name, or either
    of those nested under a 'policies' key.
    """
    node = d
    if isinstance(node, dict) and "policies" in node:
        node = node["policies"]

    if isinstance(node, list):
        rec = next((r for r in node
                    if isinstance(r, dict) and r.get("policy") == "agent"), None)
        if rec is None:
            rec = next((r for r in node
                        if isinstance(r, dict)
                        and "agent" in str(r.get("name", r.get("policy", "")))), None)
    elif isinstance(node, dict):
        rec = node.get("agent")
    else:
        rec = None

    if rec is None:
        raise SystemExit(
            "Could not find the agent record. Top-level type: "
            f"{type(d).__name__}. First element/keys: "
            f"{d[0] if isinstance(d, list) and d else list(d)[:8]}"
        )

    for k in ("net_rupees", "net", "net_rs"):
        if k in rec:
            return rec[k]
    raise SystemExit(f"No net_rupees field. Keys on agent record: {sorted(rec)}")


xs = [f for f, _ in rows]
net = [dig(d) for _, d in rows]

print(f"{'floor':>6} {'net_rupees':>12}")
for f, n in zip(xs, net):
    print(f"{f:6.2f} {n:12,.0f}")

fig, ax = plt.subplots(figsize=(6, 4))
ax.plot(xs, net, "o-", color="#2563eb")
ax.axhline(net[0], ls="--", lw=1, color="grey", label="no floor")
ax.set_xlabel("confidence floor on p(win)")
ax.set_ylabel("net rupees")
ax.set_title("Does refusing low-confidence cases help?")
ax.legend(frameon=False)
fig.tight_layout()
out = os.path.join(HERE, "..", "data", "floor_curve.png")
fig.savefig(out, dpi=140)
print("wrote data/floor_curve.png")