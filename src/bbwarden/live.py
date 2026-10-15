"""Live Bitbucket backends (Cloud and Data Center) built on atlassian-python-api sessions."""
import os
from urllib.parse import urlsplit

from .http import AuthError, BBWardenError, Http, ManualStep
from .model import Workspace

DC_PERM = {"REPO_READ": "READ", "REPO_WRITE": "WRITE", "REPO_ADMIN": "ADMIN",
           "PROJECT_READ": "READ", "PROJECT_WRITE": "WRITE", "PROJECT_ADMIN": "ADMIN"}
CLOUD_PERM = {"read": "READ", "write": "WRITE", "admin": "ADMIN", "create-repo": "WRITE"}


__all__ = ["ManualStep"]  # re-exported for callers

GLOBAL_ADMIN = ("ADMIN", "SYS_ADMIN")   # Data Center global permissions that imply repo admin


def _optional(ws, what, fn):
    """Run a load step that needs extra rights. 403/404 become a note instead of a crash."""
    try:
        fn()
    except BBWardenError as e:
        if e.status in (403, 404):
            ws.notes.append(f"{what} not loaded (HTTP {e.status}); effective access may be incomplete")
        else:
            raise


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
    u = urlsplit(url)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))):
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
            proj_public = bool(proj.get("public"))
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
                    "public": proj_public or bool(r.get("public")),
                    "users": {u["user"]["name"]: _perm(DC_PERM, u["permission"])
                              for u in self.h.paginate(f"{p}/projects/{k}/repos/{s}/permissions/users")},
                    "groups": {g["group"]["name"]: _perm(DC_PERM, g["permission"])
                               for g in self.h.paginate(f"{p}/projects/{k}/repos/{s}/permissions/groups")},
                }
        def admins():
            for x in self.h.paginate(f"{p}/admin/permissions/users"):
                if x["permission"] in GLOBAL_ADMIN:
                    ws.admins[x["user"]["name"]] = f"global:{x['permission']}"

        def admin_groups():
            for x in self.h.paginate(f"{p}/admin/permissions/groups"):
                if x["permission"] in GLOBAL_ADMIN:
                    ws.admin_groups[x["group"]["name"]] = f"global:{x['permission']}"

        _optional(ws, "global admin users", admins)
        _optional(ws, "global admin groups", admin_groups)
        _fill(ws, lambda g: [m["name"] for m in self.h.paginate(
            f"{p}/admin/groups/more-members", {"context": g})],
            lambda: {u["name"]: u.get("active") for u in self.h.paginate(f"{p}/admin/users")})
        return ws

    def load_memberships(self, ws, user):
        """Add every group the user belongs to, not only groups that hold a grant."""
        found = False
        for g in self.h.paginate("rest/api/1.0/admin/users/more-members", {"context": user}):
            found = True
            members = ws.groups.setdefault(g["name"], [])
            if user not in members:
                members.append(user)
        if found:   # only a real membership makes the user known; a typo stays unknown
            ws.users.setdefault(user, {"active": None})

    def remove_global(self, user):
        self.h.request("DELETE", "rest/api/1.0/admin/permissions/users", params={"name": user})

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
    """Users are keyed by account_id (stable and unique); nicknames are display only."""
    cloud = True

    def __init__(self, http, workspace):
        self.h, self.w = http, workspace
        self.uuids = {}   # account_id -> uuid
        self.names = {}   # account_id -> nickname

    def _user(self, u):
        key = u.get("account_id") or u["uuid"]
        self.uuids[key] = u["uuid"]
        self.names[key] = u.get("nickname") or u.get("display_name") or key
        return key

    def _uuid(self, user):
        if user not in self.uuids:
            raise BBWardenError(f"unknown Cloud user {user}: pass the account_id shown by bbwarden")
        return self.uuids[user]

    def load(self):
        ws, w = Workspace(), self.w

        def owners():
            for x in self.h.paginate(f"2.0/workspaces/{w}/permissions"):
                if x.get("permission") == "owner":
                    ws.admins[self._user(x["user"])] = "workspace:owner"

        _optional(ws, "workspace owners", owners)
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
                "public": r.get("is_private") is False,
                "users": {self._user(x["user"]): _perm(CLOUD_PERM, x["permission"]) for x in
                          self.h.paginate(f"2.0/repositories/{w}/{s}/permissions-config/users")},
                "groups": {x["group"]["slug"]: _perm(CLOUD_PERM, x["permission"]) for x in
                           self.h.paginate(f"2.0/repositories/{w}/{s}/permissions-config/groups")},
            }
        # Legacy 1.0 groups API: Bitbucket Cloud has no 2.0 group membership endpoint yet.
        _fill(ws, lambda g: [self._user(m) for m in self.h.get(f"1.0/groups/{w}/{g}/members")], None)
        for k, n in self.names.items():
            ws.users.setdefault(k, {"active": None})["name"] = n
        return ws

    def load_memberships(self, ws, user):
        """Load every workspace group (legacy 1.0 API) so offboard sees all memberships."""
        for g in self.h.get(f"1.0/groups/{self.w}"):
            if not isinstance(g.get("members"), list):
                raise BBWardenError(f"Bitbucket returned no member list for group {g.get('slug')}; "
                                    "refusing to offboard on incomplete data")
            ws.groups[g["slug"]] = [self._user(m) for m in g["members"]]
        for k, n in self.names.items():
            ws.users.setdefault(k, {"active": None})["name"] = n

    def remove_global(self, user):
        raise ManualStep("Bitbucket Cloud has no API to remove a workspace owner; "
                            "remove them in Workspace settings, then re-run")

    def remove_user(self, ws, scope, key, user):
        self._uuid(user)   # fail on unknown users instead of guessing
        path = (f"2.0/workspaces/{self.w}/projects/{key}/permissions-config/users/{user}"
                if scope == "project" else
                f"2.0/repositories/{self.w}/{key}/permissions-config/users/{user}")
        self.h.request("DELETE", path)

    def grant_group(self, ws, key, group, perm):
        self.h.request("PUT", f"2.0/repositories/{self.w}/{key}/permissions-config/groups/{group}",
                       json={"permission": perm.lower()})

    def remove_member(self, group, user):
        self.h.request("DELETE", f"1.0/groups/{self.w}/{group}/members/{self._uuid(user)}")


def _fill(ws, members, statuses):
    granted = [g for obj in list(ws.projects.values()) + list(ws.repos.values()) for g in obj["groups"]]
    for g in granted + list(ws.admin_groups):
        if g not in ws.groups:
            ws.groups[g] = members(g)
    names = {u for m in ws.groups.values() for u in m}
    for obj in list(ws.projects.values()) + list(ws.repos.values()):
        names |= set(obj["users"])
    names |= set(ws.admins)
    # None means unknown: Cloud exposes no account status, and Data Center may omit users.
    active = statuses() if statuses else {}
    ws.users = {n: {"active": active.get(n)} for n in names}


def crowd_status(http, users):
    """Look up active flag per username in Crowd. A 404 (unknown user) counts as disabled;
    any other error is raised."""
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


CLOUD_HOSTS = ("bitbucket.org", "api.bitbucket.org")


def is_cloud(url):
    return (urlsplit(url).hostname or "").lower() in CLOUD_HOSTS


def backend_from_env(env=None, session_factory=make_session, **http_kw):
    env = os.environ if env is None else env
    url, user, token = creds_from_env(env)
    cloud = is_cloud(url)
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
