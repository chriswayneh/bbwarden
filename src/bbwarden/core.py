"""Analysis and fix planning. Pure functions over a Workspace."""

import csv
import logging
from typing import Any

from .http import BBWardenError, ManualStep
from .model import RANK, rank

log = logging.getLogger("bbwarden")


class AmbiguousUser(KeyError):
    pass


class UnknownUser(KeyError):
    pass


class BadIdpFile(ValueError):
    pass


PUBLIC = "(anyone)"


def label(ws, u):
    """Display name: 'nickname (account_id)' when the key is an opaque id, else the key."""
    name = ws.users.get(u, {}).get("name")
    return f"{name} ({u})" if name and name != u else u


def resolve_user(ws, name):
    """Map a CLI user argument to a user key. Matches a key exactly, else a unique display name."""
    if name in ws.users:
        return name
    hits = sorted(k for k, v in ws.users.items() if v.get("name") == name)
    if len(hits) > 1:
        raise AmbiguousUser(
            f"ambiguous user {name}: {', '.join(hits)} (pass one account_id)"
        )
    if not hits:
        raise UnknownUser(
            f"unknown user {name}: no grant or group membership found "
            "(Cloud: pass an account_id or nickname shown by bbwarden)"
        )
    return hits[0]


def describe_error(e):
    """Message for logs and the partial-apply report. Our own errors are written to be safe to
    show; for anything else only the type is shown, since str(e) could carry secrets."""
    return str(e) if isinstance(e, BBWardenError) else type(e).__name__


class PartialApply(Exception):
    """An --apply run failed partway. Carries the steps that finished and the failed step."""

    def __init__(self, done, failed, error, pending=()):
        super().__init__(describe_error(error))
        self.done, self.failed, self.error, self.pending = (
            done,
            failed,
            error,
            list(pending),
        )


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
    for u, src in ws.admins.items():
        yield u, "ADMIN", src
    for g, src in ws.admin_groups.items():
        for u in ws.groups.get(g, []):
            yield u, "ADMIN", f"{src}/group:{g}"


def resolve_repo(ws, name):
    """Accept a repo key, or a bare slug when it is unique (Data Center keys are PROJECT/slug)."""
    if name in ws.repos:
        return name
    hits = [k for k in ws.repos if k.split("/")[-1] == name]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise AmbiguousRepo(
            f"ambiguous repo {name}: use one of {', '.join(sorted(hits))}"
        )
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
    best: dict[tuple[str, str], dict[str, Any]] = {}
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
        rows.append(
            {
                "repo": s,
                "user": label(ws, u),
                "effective": v["perm"],
                "sources": ", ".join(sorted(set(v["sources"]))),
                "flag": flag,
            }
        )
    for s in sorted(slugs):
        if ws.repos[s].get("public"):
            rows.append(
                {
                    "repo": s,
                    "user": PUBLIC,
                    "effective": "READ",
                    "sources": "public",
                    "flag": "PUBLIC",
                }
            )
    rows.sort(key=lambda r: (r["repo"], r["user"] == PUBLIC))
    return rows


def direct(ws):
    rows = []
    for k, p in sorted(ws.projects.items()):
        for u, perm in sorted(p["users"].items()):
            rows.append(
                {
                    "scope": "project",
                    "name": k,
                    "user": label(ws, u),
                    "permission": perm,
                }
            )
    for s, r in sorted(ws.repos.items()):
        for u, perm in sorted(r["users"].items()):
            rows.append(
                {"scope": "repo", "name": s, "user": label(ws, u), "permission": perm}
            )
    return rows


TRUE = ("true", "1", "yes", "active")
FALSE = ("false", "0", "no", "inactive", "disabled")


def load_idp_csv(path):
    """Strict CSV with columns user,active. Bad rows raise BadIdpFile with the line number."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        if not rd.fieldnames or not {"user", "active"} <= {
            c.strip() for c in rd.fieldnames
        }:
            raise BadIdpFile(f"{path}: needs columns user,active")
        for row in rd:
            line = rd.line_num
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            user, val = row.get("user", ""), row.get("active", "").lower()
            if not user:
                raise BadIdpFile(f"{path} line {line}: empty user")
            if val not in TRUE + FALSE:
                raise BadIdpFile(
                    f"{path} line {line}: active must be one of "
                    f"{'/'.join(TRUE + FALSE)}, got {val!r}"
                )
            if user in out:
                raise BadIdpFile(f"{path} line {line}: duplicate user {user}")
            out[user] = val in TRUE
    return out


def orphans(ws, status):
    rows = []
    for s in sorted(ws.repos):
        seen: dict[str, list[Any]] = {}
        for u, p, src in _grants(ws, s):
            name = ws.users.get(u, {}).get("name")
            st = status[u] if u in status else status.get(name)
            if st is not True:
                seen.setdefault(u, ["disabled" if st is False else "missing", []])[
                    1
                ].append(f"{src}:{p}")
        for u, (st, srcs) in sorted(seen.items()):
            rows.append(
                {
                    "repo": s,
                    "user": label(ws, u),
                    "access": ", ".join(srcs),
                    "idp_status": st,
                }
            )
    return rows


def _effective(ws, slug):
    out: dict[str, int] = {}
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
        if p not in RANK:
            plan.append(
                {
                    "repo": slug,
                    "user": label(ws, u),
                    "key": u,
                    "action": "manual",
                    "group": "",
                    "detail": f"unknown permission {p}; review by hand",
                }
            )
            continue
        mine = sorted(g for g, m in ws.groups.items() if u in m)
        groups = [
            g for g in mine if all(eff.get(m, 0) >= rank(p) for m in ws.groups[g])
        ]
        if mine and not groups:
            plan.append(
                {
                    "repo": slug,
                    "user": label(ws, u),
                    "key": u,
                    "action": "manual",
                    "group": "",
                    "detail": f"every group of {label(ws, u)} ({', '.join(mine)}) would widen access; "
                    f"create a narrower group or keep direct {p}",
                }
            )
        elif groups:
            plan.append(
                {
                    "repo": slug,
                    "user": label(ws, u),
                    "key": u,
                    "action": "replace",
                    "group": groups[0],
                    "detail": f"grant group {groups[0]} {p}; remove direct {p}",
                }
            )
        else:
            plan.append(
                {
                    "repo": slug,
                    "user": label(ws, u),
                    "key": u,
                    "action": "manual",
                    "group": "",
                    "detail": f"no granted group contains {label(ws, u)}; create one or keep direct {p}",
                }
            )
    return plan


def _run_steps(steps):
    """Run (label, fn) pairs in order. On failure raise PartialApply listing finished labels."""
    done: list[str] = []
    for i, (label, fn) in enumerate(steps):
        try:
            fn()
        except Exception as e:
            log.error(
                "apply failed at step %s after %d finished: %s",
                label,
                len(done),
                describe_error(e),
            )
            for d in done:
                log.error("finished: %s", d)
            raise PartialApply(done, label, e, [lb for lb, _ in steps[i + 1 :]]) from e
        done.append(label)
        log.info("finished: %s", label)
    return done


def apply_regroup(ws, plan, backend=None):
    """Grant the group first, then drop the direct grant, so access is never lost mid-way."""
    steps = []
    for step in plan:
        if step["action"] != "replace":
            continue
        key, u, g = step["repo"], step["key"], step["group"]
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

        steps += [
            (f"grant group {g} {perm} on repo {key}", grant),
            (f"remove direct {step['user']} from repo {key}", remove),
        ]
    return _run_steps(steps)


def offboard(ws, user, memberships=True):
    plan = []
    for k, p in sorted(ws.projects.items()):
        if user in p["users"]:
            plan.append(
                {
                    "scope": "project",
                    "name": k,
                    "action": "remove direct grant",
                    "detail": p["users"][user],
                }
            )
    for s, r in sorted(ws.repos.items()):
        if user in r["users"]:
            plan.append(
                {
                    "scope": "repo",
                    "name": s,
                    "action": "remove direct grant",
                    "detail": r["users"][user],
                }
            )
    for g, m in sorted(ws.groups.items()):
        if memberships and user in m:
            plan.append(
                {
                    "scope": "group",
                    "name": g,
                    "action": "remove membership",
                    "detail": "",
                }
            )
    # Last: may be impossible by API (Cloud owners), so it must not block the rest. Any
    # direct global permission counts, not only admin levels (LICENSED_USER, PROJECT_CREATE).
    if user in ws.admins or user in ws.global_perms:
        kind, level = ws.admins.get(user, f"global:{ws.global_perms.get(user)}").split(
            ":", 1
        )
        action = (
            "remove all global permissions"
            if kind == "global"
            else f"remove {kind} {level} (manual on Cloud)"
        )
        plan.append(
            {"scope": "global", "name": kind, "action": action, "detail": level}
        )
    return plan


def apply_offboard(ws, user, plan, backend=None):
    def do(step):
        if backend:
            if step["scope"] == "global":
                backend.remove_global(user)
            elif step["scope"] == "group":
                backend.remove_member(step["name"], user)
            else:
                backend.remove_user(ws, step["scope"], step["name"], user)
        if step["scope"] == "global":
            ws.admins.pop(user, None)
            ws.global_perms.pop(user, None)
        elif step["scope"] == "project":
            ws.projects[step["name"]]["users"].pop(user, None)
        elif step["scope"] == "repo":
            ws.repos[step["name"]]["users"].pop(user, None)
        else:
            ws.groups[step["name"]].remove(user)

    lab = lambda s: f"{s['action']} {label(ws, user)}: {s['scope']} {s['name']}"
    regular = [s for s in plan if s["scope"] != "global"]
    globals_ = [s for s in plan if s["scope"] == "global"]
    try:
        done = _run_steps([(lab(s), lambda s=s: do(s)) for s in regular])
    except PartialApply as e:
        e.pending.extend(lab(s) for s in globals_)  # global steps never ran either
        raise
    for i, s in enumerate(globals_):
        try:
            do(s)
        except ManualStep as e:  # no removal API (Cloud owner): keep what finished
            log.warning("manual step needed: %s: %s", lab(s), e)
            ws.manual.append((lab(s), str(e)))
            continue
        except Exception as e:
            log.error(
                "apply failed at step %s after %d finished: %s",
                lab(s),
                len(done),
                describe_error(e),
            )
            raise PartialApply(
                done, lab(s), e, [lab(x) for x in globals_[i + 1 :]]
            ) from e
        done.append(lab(s))
    return done
