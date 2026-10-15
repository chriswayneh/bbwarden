"""Live Bitbucket backends (Cloud and Data Center) built on atlassian-python-api sessions."""
import os

from .http import AuthError, BBWardenError, Http
from .model import Workspace

DC_PERM = {"REPO_READ": "READ", "REPO_WRITE": "WRITE", "REPO_ADMIN": "ADMIN",
           "PROJECT_READ": "READ", "PROJECT_WRITE": "WRITE", "PROJECT_ADMIN": "ADMIN"}
CLOUD_PERM = {"read": "READ", "write": "WRITE", "admin": "ADMIN", "create-repo": "WRITE"}


def _perm(table, raw):
    """Map an API permission name; unknown values pass through upper-cased instead of crashing."""
    return table.get(raw, str(raw).upper())


def creds_from_env(env=None):
    env = os.environ if env is None else env
    url, user, token = env.get("BBWARDEN_URL"), env.get("BBWARDEN_USER"), env.get("BBWARDEN_TOKEN")
    missing = [n for n, v in (("BBWARDEN_URL", url), ("BBWARDEN_USER", user),
                              ("BBWARDEN_TOKEN", token)) if not v]
    if missing:
        raise AuthError(f"missing {', '.join(missing)}: set them in the environment or use --demo")
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        raise BBWardenError("BBWARDEN_URL must use https:// so credentials are not sent in clear text")
    return url, user, token


def make_session(url, user, token, cloud):  # pragma: no cover - thin wrapper over the library
    if cloud:
        from atlassian.bitbucket import Cloud
        return Cloud(url="https://api.bitbucket.org/", username=user, password=token).session
    from atlassian import Bitbucket
    return Bitbucket(url=url, username=user, password=token).session


class DataCenter:
    cloud = False

    def __init__(self, http):
        self.h = http

    def load(self):
        ws, p = Workspace(), "rest/api/1.0"
        for proj in self.h.paginate(f"{p}/projects"):
            k = proj["key"]
            ws.projects[k] = {
                "users": {u["user"]["name"]: _perm(DC_PERM, u["permission"])
                          for u in self.h.paginate(f"{p}/projects/{k}/permissions/users")},
                "groups": {g["group"]["name"]: _perm(DC_PERM, g["permission"])
                           for g in self.h.paginate(f"{p}/projects/{k}/permissions/groups")},
            }
            for r in self.h.paginate(f"{p}/projects/{k}/repos"):
                s = r["slug"]
                ws.repos[f"{k}/{s}"] = {
                    "project": k,
                    "users": {u["user"]["name"]: _perm(DC_PERM, u["permission"])
                              for u in self.h.paginate(f"{p}/projects/{k}/repos/{s}/permissions/users")},
                    "groups": {g["group"]["name"]: _perm(DC_PERM, g["permission"])
                               for g in self.h.paginate(f"{p}/projects/{k}/repos/{s}/permissions/groups")},
                }
        _fill(ws, lambda g: [m["name"] for m in self.h.paginate(
            f"{p}/admin/groups/more-members", {"context": g})],
            lambda: {u["name"]: u.get("active") for u in self.h.paginate(f"{p}/admin/users")})
        return ws

    def remove_user(self, ws, scope, key, user):
        p = "rest/api/1.0"
        path = (f"{p}/projects/{key}/permissions/users" if scope == "project" else
                f"{p}/projects/{ws.repos[key]['project']}/repos/{key.split('/', 1)[1]}/permissions/users")
        self.h.request("DELETE", path, params={"name": user})

    def grant_group(self, ws, key, group, perm):
        r = ws.repos[key]
        self.h.request("PUT", f"rest/api/1.0/projects/{r['project']}/repos/{key.split('/', 1)[1]}"
                       "/permissions/groups", params={"name": group, "permission": f"REPO_{perm}"})

    def remove_member(self, group, user):
        self.h.request("POST", "rest/api/1.0/admin/users/remove-group",
                       json={"context": user, "itemName": group})


class CloudBackend:
    cloud = True

    def __init__(self, http, workspace):
        self.h, self.w = http, workspace
        self.uuids = {}

    def _user(self, u):
        name = u.get("nickname") or u.get("display_name") or u["uuid"]
        self.uuids[name] = u["uuid"]
        return name

    def load(self):
        ws, w = Workspace(), self.w
        for proj in self.h.paginate(f"2.0/workspaces/{w}/projects"):
            k = proj["key"]
            ws.projects[k] = {
                "users": {self._user(x["user"]): _perm(CLOUD_PERM, x["permission"]) for x in
                          self.h.paginate(f"2.0/workspaces/{w}/projects/{k}/permissions-config/users")},
                "groups": {x["group"]["slug"]: _perm(CLOUD_PERM, x["permission"]) for x in
                           self.h.paginate(f"2.0/workspaces/{w}/projects/{k}/permissions-config/groups")},
            }
        for r in self.h.paginate(f"2.0/repositories/{w}"):
            s = r["slug"]
            ws.repos[s] = {
                "project": (r.get("project") or {}).get("key", ""),
                "users": {self._user(x["user"]): _perm(CLOUD_PERM, x["permission"]) for x in
                          self.h.paginate(f"2.0/repositories/{w}/{s}/permissions-config/users")},
                "groups": {x["group"]["slug"]: _perm(CLOUD_PERM, x["permission"]) for x in
                           self.h.paginate(f"2.0/repositories/{w}/{s}/permissions-config/groups")},
            }
        _fill(ws, lambda g: [self._user(m) for m in self.h.get(f"1.0/groups/{w}/{g}/members")], None)
        return ws

    def remove_user(self, ws, scope, key, user):
        uid = self.uuids.get(user, user)
        path = (f"2.0/workspaces/{self.w}/projects/{key}/permissions-config/users/{uid}"
                if scope == "project" else
                f"2.0/repositories/{self.w}/{key}/permissions-config/users/{uid}")
        self.h.request("DELETE", path)

    def grant_group(self, ws, key, group, perm):
        self.h.request("PUT", f"2.0/repositories/{self.w}/{key}/permissions-config/groups/{group}",
                       json={"permission": perm.lower()})

    def remove_member(self, group, user):
        self.h.request("DELETE", f"1.0/groups/{self.w}/{group}/members/{self.uuids.get(user, user)}")


def _fill(ws, members, statuses):
    for obj in list(ws.projects.values()) + list(ws.repos.values()):
        for g in obj["groups"]:
            if g not in ws.groups:
                ws.groups[g] = members(g)
    names = {u for m in ws.groups.values() for u in m}
    for obj in list(ws.projects.values()) + list(ws.repos.values()):
        names |= set(obj["users"])
    # None means unknown: Cloud exposes no account status, and Data Center may omit users.
    active = statuses() if statuses else {}
    ws.users = {n: {"active": active.get(n)} for n in names}


def crowd_status(http, users):
    """Look up active flag per user in Crowd. Unknown users are treated as disabled."""
    out = {}
    for u in users:
        try:
            out[u] = bool(http.get("rest/usermanagement/1/user", params={"username": u}).get("active"))
        except BBWardenError as e:
            if isinstance(e, AuthError):
                raise
            if "HTTP 404" in str(e):
                out[u] = False
            else:
                raise
    return out


def backend_from_env(env=None, session_factory=make_session, **http_kw):
    env = os.environ if env is None else env
    url, user, token = creds_from_env(env)
    cloud = "bitbucket.org" in url
    if cloud:
        w = env.get("BBWARDEN_WORKSPACE")
        if not w:
            raise BBWardenError("missing BBWARDEN_WORKSPACE (your Bitbucket Cloud workspace slug)")
        http = Http(session_factory(url, user, token, True), "https://api.bitbucket.org", **http_kw)
        return CloudBackend(http, w)
    return DataCenter(Http(session_factory(url, user, token, False), url, **http_kw))


def crowd_from_env(env=None, session_factory=None, **http_kw):
    env = os.environ if env is None else env
    url, app, pw = env.get("CROWD_URL"), env.get("CROWD_APP"), env.get("CROWD_PASSWORD")
    if not (url and app and pw):
        raise AuthError("--idp crowd needs CROWD_URL, CROWD_APP and CROWD_PASSWORD (Crowd application "
                        "credentials), or use --idp csv")
    if session_factory is None:  # pragma: no cover
        import requests
        s = requests.Session()
        s.auth = (app, pw)
        s.headers["Accept"] = "application/json"
    else:
        s = session_factory()
    return Http(s, url, **http_kw)
