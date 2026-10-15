"""Analysis and fix planning. Pure functions over a Workspace."""
import csv
import logging

from .model import rank

log = logging.getLogger("bbwarden")


class PartialApply(Exception):
    """An --apply run failed partway. Carries the steps that finished and the failed step."""

    def __init__(self, done, failed, error, pending=()):
        super().__init__(str(error))
        self.done, self.failed, self.error, self.pending = done, failed, error, list(pending)


class AmbiguousRepo(KeyError):
    pass


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


def resolve_repo(ws, name):
    """Accept a repo key, or a bare slug when it is unique (Data Center keys are PROJECT/slug)."""
    if name in ws.repos:
        return name
    hits = [k for k in ws.repos if k.split("/")[-1] == name]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise AmbiguousRepo(f"ambiguous repo {name}: use one of {', '.join(sorted(hits))}")
    raise KeyError(f"unknown repo: {name}")


def who(ws, target):
    if target in ws.projects and target not in ws.repos:
        slugs = [s for s, r in ws.repos.items() if r["project"] == target]
    else:
        try:
            slugs = [resolve_repo(ws, target)]
        except AmbiguousRepo:
            raise
        except KeyError:
            slugs = []
    if not slugs:
        raise KeyError(f"unknown repo or project: {target}")
    best = {}
    for s in slugs:
        for u, p, src in _grants(ws, s):
            key = (s, u)
            cur = best.setdefault(key, {"perm": p, "sources": []})
            if rank(p) > rank(cur["perm"]):
                cur["perm"] = p
            cur["sources"].append(src)
    rows = []
    for (s, u), v in sorted(best.items()):
        active = ws.users.get(u, {}).get("active")
        flag = "DISABLED" if active is False else ("UNKNOWN" if active is None else "")
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


def _effective(ws, slug):
    out = {}
    for u, p, _ in _grants(ws, slug):
        out[u] = max(out.get(u, 0), rank(p))
    return out


def regroup(ws, slug):
    """Plan: for each direct grant, pick a group the user belongs to whose every member
    already has at least that access on the repo, so the grant widens nobody's access.
    Otherwise flag the grant for manual handling."""
    slug = resolve_repo(ws, slug)
    repo = ws.repos[slug]
    eff = _effective(ws, slug)
    plan = []
    for u, p in sorted(repo["users"].items()):
        mine = sorted(g for g, m in ws.groups.items() if u in m)
        groups = [g for g in mine if all(eff.get(m, 0) >= rank(p) for m in ws.groups[g])]
        if mine and not groups:
            plan.append({"repo": slug, "user": u, "action": "manual", "group": "",
                         "detail": f"every group of {u} ({', '.join(mine)}) would widen access; "
                                   f"create a narrower group or keep direct {p}"})
        elif groups:
            plan.append({"repo": slug, "user": u, "action": "replace", "group": groups[0],
                         "detail": f"grant group {groups[0]} {p}; remove direct {p}"})
        else:
            plan.append({"repo": slug, "user": u, "action": "manual", "group": "",
                         "detail": f"no group contains {u}; create one or keep direct {p}"})
    return plan


def _run_steps(steps):
    """Run (label, fn) pairs in order. On failure raise PartialApply listing finished labels."""
    done = []
    for i, (label, fn) in enumerate(steps):
        try:
            fn()
        except Exception as e:
            log.error("apply failed at step %r after %d finished: %s", label, len(done), e)
            for d in done:
                log.error("finished: %s", d)
            raise PartialApply(done, label, e, [lb for lb, _ in steps[i + 1:]]) from e
        done.append(label)
        log.info("finished: %s", label)
    return done


def apply_regroup(ws, plan, backend=None):
    """Grant the group first, then drop the direct grant, so access is never lost mid-way."""
    steps = []
    for step in plan:
        if step["action"] != "replace":
            continue
        key, u, g = step["repo"], step["user"], step["group"]
        repo = ws.repos[key]
        perm = repo["users"][u]

        def grant(key=key, g=g, perm=perm, repo=repo):
            if rank(repo["groups"].get(g)) < rank(perm):
                if backend:
                    backend.grant_group(ws, key, g, perm)
                repo["groups"][g] = perm

        def remove(key=key, u=u, repo=repo):
            if backend:
                backend.remove_user(ws, "repo", key, u)
            del repo["users"][u]

        steps += [(f"grant group {g} {perm} on repo {key}", grant),
                  (f"remove direct {u} from repo {key}", remove)]
    return _run_steps(steps)


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


def apply_offboard(ws, user, plan, backend=None):
    def do(step):
        if backend:
            if step["scope"] == "group":
                backend.remove_member(step["name"], user)
            else:
                backend.remove_user(ws, step["scope"], step["name"], user)
        if step["scope"] == "project":
            ws.projects[step["name"]]["users"].pop(user, None)
        elif step["scope"] == "repo":
            ws.repos[step["name"]]["users"].pop(user, None)
        else:
            ws.groups[step["name"]].remove(user)

    return _run_steps([(f"{s['action']} {user}: {s['scope']} {s['name']}", lambda s=s: do(s))
                       for s in plan])
