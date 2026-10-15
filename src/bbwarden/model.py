"""Backend-neutral workspace model plus demo data and live adapters."""
from dataclasses import dataclass, field

RANK = {"READ": 1, "WRITE": 2, "ADMIN": 3}


@dataclass
class Workspace:
    users: dict = field(default_factory=dict)       # user -> {"active": bool}
    groups: dict = field(default_factory=dict)      # group -> [users]
    projects: dict = field(default_factory=dict)    # key -> {"users": {u: perm}, "groups": {g: perm}}
    repos: dict = field(default_factory=dict)       # slug -> {"project": key, "users": {...}, "groups": {...}}


def demo_workspace():
    return Workspace(
        users={"alice": {"active": True}, "bob": {"active": True}, "carol": {"active": True},
               "dave": {"active": False}, "erin": {"active": True}, "frank": {"active": False}},
        groups={"devs": ["alice", "bob"], "ops": ["carol"], "admins": ["alice"]},
        projects={
            "CORE": {"users": {"dave": "WRITE"}, "groups": {"devs": "WRITE", "admins": "ADMIN"}},
            "OPS": {"users": {}, "groups": {"ops": "WRITE"}},
        },
        repos={
            "api": {"project": "CORE", "users": {"erin": "WRITE", "bob": "ADMIN"}, "groups": {}},
            "web": {"project": "CORE", "users": {"frank": "READ"}, "groups": {"ops": "READ"}},
            "infra": {"project": "OPS", "users": {"erin": "WRITE"}, "groups": {}},
        },
    )


def load_live(url, username, token, cloud=False, workspace=None):  # pragma: no cover
    """Build a Workspace from Bitbucket Data Center via atlassian-python-api."""
    from atlassian import Bitbucket
    if cloud:
        raise NotImplementedError("Bitbucket Cloud live loading lands in milestone 2; use --demo")
    bb = Bitbucket(url=url, username=username, password=token)
    ws = Workspace()
    for p in bb.project_list():
        key = p["key"]
        ws.projects[key] = {
            "users": {u["user"]["name"]: u["permission"].split("_")[-1] for u in bb.project_users(key)},
            "groups": {g["group"]["name"]: g["permission"].split("_")[-1] for g in bb.project_groups(key)},
        }
        for r in bb.repo_list(key):
            s = r["slug"]
            ws.repos[s] = {
                "project": key,
                "users": {u["user"]["name"]: u["permission"].split("_")[-1] for u in bb.repo_users(key, s)},
                "groups": {g["group"]["name"]: g["permission"].split("_")[-1] for g in bb.repo_groups(key, s)},
            }
    names = set()
    for obj in list(ws.projects.values()) + list(ws.repos.values()):
        names |= set(obj["users"])
        for g in obj["groups"]:
            if g not in ws.groups:
                ws.groups[g] = [m["name"] for m in bb.group_members(g)]
            names |= set(ws.groups[g])
    ws.users = {n: {"active": True} for n in names}
    return ws
