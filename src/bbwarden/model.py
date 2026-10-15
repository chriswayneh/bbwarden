"""Backend-neutral workspace model plus demo data and live adapters."""
from dataclasses import dataclass, field

RANK = {"READ": 1, "WRITE": 2, "ADMIN": 3}


def rank(perm):
    return RANK.get(perm, 0)


@dataclass
class Workspace:
    users: dict = field(default_factory=dict)       # user -> {"active": bool}
    groups: dict = field(default_factory=dict)      # group -> [users]
    projects: dict = field(default_factory=dict)    # key -> {"users": {u: perm}, "groups": {g: perm}}
    repos: dict = field(default_factory=dict)       # key -> {"project", "users", "groups", "public"?}
    admins: dict = field(default_factory=dict)      # user -> source, e.g. "global:SYS_ADMIN"
    admin_groups: dict = field(default_factory=dict)  # group -> source
    notes: list = field(default_factory=list)       # gaps in what could be loaded
    manual: list = field(default_factory=list)      # apply steps that must be done by hand


def demo_workspace():
    return Workspace(
        users={"alice": {"active": True}, "bob": {"active": True}, "carol": {"active": True},
               "dave": {"active": False}, "erin": {"active": True}, "frank": {"active": False},
               "root": {"active": True}},
        groups={"devs": ["alice", "bob"], "ops": ["carol"], "admins": ["alice"]},
        projects={
            "CORE": {"users": {"dave": "WRITE"}, "groups": {"devs": "WRITE", "admins": "ADMIN"}},
            "OPS": {"users": {}, "groups": {"ops": "WRITE"}},
        },
        repos={
            "api": {"project": "CORE", "users": {"erin": "WRITE", "bob": "ADMIN"}, "groups": {}},
            "web": {"project": "CORE", "users": {"frank": "READ"}, "groups": {"ops": "READ"},
                    "public": True},
            "infra": {"project": "OPS", "users": {"erin": "WRITE"}, "groups": {}},
        },
        admins={"root": "global:SYS_ADMIN"},
    )
