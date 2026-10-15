"""Analysis and fix planning. Pure functions over a Workspace."""
import csv
from .model import RANK


def _grants(ws, slug):
    """Yield (user, perm, source) for a repo, including project inheritance."""
    repo = ws.repos[slug]
    proj = ws.projects.get(repo["project"], {"users": {}, "groups": {}})
    for u, p in repo["users"].items():
        yield u, p, "direct"
    for g, p in repo["groups"].items():
        for u in ws.groups.get(g, []):
            yield u, p, f"group:{g}"
    for u, p in proj["users"].items():
        yield u, p, f"project:{repo['project']}"
    for g, p in proj["groups"].items():
        for u in ws.groups.get(g, []):
            yield u, p, f"project:{repo['project']}/group:{g}"


def who(ws, target):
    slugs = [target] if target in ws.repos else [s for s, r in ws.repos.items() if r["project"] == target]
    if not slugs:
        raise KeyError(f"unknown repo or project: {target}")
    best = {}
    for s in slugs:
        for u, p, src in _grants(ws, s):
            key = (s, u)
            cur = best.setdefault(key, {"perm": p, "sources": []})
            if RANK[p] > RANK[cur["perm"]]:
                cur["perm"] = p
            cur["sources"].append(src)
    rows = []
    for (s, u), v in sorted(best.items()):
        flag = "" if ws.users.get(u, {}).get("active", True) else "DISABLED"
        rows.append({"repo": s, "user": u, "effective": v["perm"],
                     "sources": ", ".join(sorted(set(v["sources"]))), "flag": flag})
    return rows


def direct(ws):
    rows = []
    for k, p in sorted(ws.projects.items()):
        for u, perm in sorted(p["users"].items()):
            rows.append({"scope": "project", "name": k, "user": u, "permission": perm})
    for s, r in sorted(ws.repos.items()):
        for u, perm in sorted(r["users"].items()):
            rows.append({"scope": "repo", "name": s, "user": u, "permission": perm})
    return rows


def load_idp_csv(path):
    """CSV with columns user,active (active: true/false/1/0/yes/no)."""
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out[row["user"].strip()] = row["active"].strip().lower() in ("true", "1", "yes", "active")
    return out


def orphans(ws, status):
    rows = []
    for s in sorted(ws.repos):
        seen = {}
        for u, p, src in _grants(ws, s):
            if status.get(u, True) is False:
                seen.setdefault(u, []).append(f"{src}:{p}")
        for u, srcs in sorted(seen.items()):
            rows.append({"repo": s, "user": u, "access": ", ".join(srcs), "idp_status": "disabled"})
    return rows


def regroup(ws, slug):
    """Plan: for each direct grant, pick a group the user belongs to, else flag."""
    if slug not in ws.repos:
        raise KeyError(f"unknown repo: {slug}")
    repo = ws.repos[slug]
    plan = []
    for u, p in sorted(repo["users"].items()):
        groups = sorted(g for g, m in ws.groups.items() if u in m)
        if groups:
            plan.append({"repo": slug, "user": u, "action": "replace",
                         "detail": f"remove direct {p}; grant group {groups[0]} {p}"})
        else:
            plan.append({"repo": slug, "user": u, "action": "manual",
                         "detail": f"no group contains {u}; create one or keep direct {p}"})
    return plan


def apply_regroup(ws, plan):
    for step in plan:
        if step["action"] != "replace":
            continue
        repo = ws.repos[step["repo"]]
        perm = repo["users"].pop(step["user"])
        g = step["detail"].split("grant group ")[1].split()[0]
        if RANK.get(repo["groups"].get(g), 0) < RANK[perm]:
            repo["groups"][g] = perm


def offboard(ws, user):
    plan = []
    for k, p in sorted(ws.projects.items()):
        if user in p["users"]:
            plan.append({"scope": "project", "name": k, "action": "remove direct grant",
                         "detail": p["users"][user]})
    for s, r in sorted(ws.repos.items()):
        if user in r["users"]:
            plan.append({"scope": "repo", "name": s, "action": "remove direct grant",
                         "detail": r["users"][user]})
    for g, m in sorted(ws.groups.items()):
        if user in m:
            plan.append({"scope": "group", "name": g, "action": "remove membership", "detail": ""})
    return plan


def apply_offboard(ws, user, plan):
    for step in plan:
        if step["scope"] == "project":
            ws.projects[step["name"]]["users"].pop(user, None)
        elif step["scope"] == "repo":
            ws.repos[step["name"]]["users"].pop(user, None)
        else:
            ws.groups[step["name"]].remove(user)
