#!/usr/bin/env python3

#!/usr/bin/env python3
"""Sharif University internet portal CLI.

Passwords and session cookies are kept in memory only.
The internet connection is shared by all Linux users on this server.
"""

import getpass
import html
from html.parser import HTMLParser
import http.cookiejar
import json
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://net2.sharif.edu"
LOGIN = BASE + "/en-us/user/login/"
HOME = BASE + "/en-us/user/home/"
SESSIONS = BASE + "/en-us/user/get_user_online_session/"
CONNECT = BASE + "/en-us/user/aaa_ras_connect/"
DISCONNECT = BASE + "/en-us/user/aaa_ras_disconnect/"
TIMEOUT = 15


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.csrf = ""
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "input":
            attrs = dict(attrs)
            if attrs.get("name") == "csrfmiddlewaretoken":
                self.csrf = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            s = html.unescape(data).strip()
            if s:
                self.parts.append(s)

    @property
    def text(self):
        return " ".join(self.parts)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname != "net2.sharif.edu":
            raise RuntimeError("Unexpected portal redirect")
        return super().redirect_request(
            req, fp, code, msg, headers, newurl
        )



# SHARIF_PRIVATE_LOGIN_V2
import os as _sh_os
import stat as _sh_stat
import tempfile as _sh_tempfile
from pathlib import Path as _sh_Path

def _sh_path():
    return _sh_Path.home() / ".config" / "sharif-net" / "credentials.json"

def _sh_load():
    path = _sh_path()
    try:
        directory = path.parent.stat()
        if (
            not _sh_stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != _sh_os.getuid()
            or directory.st_mode & 0o077
        ):
            return None, None

        fd = _sh_os.open(
            path,
            _sh_os.O_RDONLY | getattr(_sh_os, "O_NOFOLLOW", 0)
        )

        with _sh_os.fdopen(fd, "r", encoding="utf-8") as f:
            st = _sh_os.fstat(f.fileno())
            if (
                not _sh_stat.S_ISREG(st.st_mode)
                or st.st_uid != _sh_os.getuid()
                or st.st_mode & 0o077
            ):
                return None, None
            obj = json.load(f)

        user, password = obj.get("username"), obj.get("password")
        if isinstance(user, str) and user and isinstance(password, str) and password:
            return user, password
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None, None

def _sh_offer(user, password):
    if not password:
        return

    print("\nSave login for this Linux user?")
    print("WARNING: Password is stored unencrypted in your private home.")

    try:
        answer = input("Save credentials? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if answer not in ("y", "yes"):
        return

    path = _sh_path()
    tmp = None

    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.is_symlink():
            raise PermissionError("Symlink not allowed")

        st = path.parent.stat()
        if st.st_uid != _sh_os.getuid():
            raise PermissionError("Wrong directory owner")

        path.parent.chmod(0o700)

        fd, tmp = _sh_tempfile.mkstemp(dir=path.parent)
        _sh_os.fchmod(fd, 0o600)

        with _sh_os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"username": user, "password": password}, f)

        _sh_os.replace(tmp, path)
        tmp = None
        print("Credentials saved for this Linux user.")

    except OSError as exc:
        print("Could not save credentials:", type(exc).__name__)
    finally:
        if tmp is not None:
            try:
                _sh_os.unlink(tmp)
            except OSError:
                pass

class Sharif:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(
                context=ssl.create_default_context()
            ),
            SameOriginRedirect(),
        )
        self.account = None

    def request(self, url, data=None, ajax=False):
        headers = {
            "User-Agent": "sharif-net/1.0",
            "Referer": HOME,
        }

        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"

        if data is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded"
            )

            if ajax:
                headers["X-Requested-With"] = "XMLHttpRequest"

            csrf = next(
                (
                    c.value for c in self.cookies
                    if c.name == "csrftoken"
                ),
                None,
            )

            if csrf:
                headers["X-CSRFToken"] = csrf

        encoded = (
            urllib.parse.urlencode(data).encode("utf-8")
            if data is not None else None
        )

        req = urllib.request.Request(
            url,
            data=encoded,
            headers=headers,
        )

        with self.opener.open(req, timeout=TIMEOUT) as response:
            return (
                response.geturl(),
                response.read().decode("utf-8", "replace"),
            )

    def login(self):
        if self.account:
            return True

        final, page = self.request(LOGIN)
        parser = PageText()
        parser.feed(page)

        if not parser.csrf:
            print("ERROR: CSRF token not found.")
            return False

        _saved_user, _saved_pass = _sh_load()
        username = _saved_user or input("Sharif username: ").strip()

        if not username:
            return False

        password = (_saved_pass if _saved_pass is not None else getpass.getpass("Sharif password (not saved): "))
        self._login_password = password

        try:
            final, page = self.request(
                LOGIN,
                {
                    "csrfmiddlewaretoken": parser.csrf,
                    "username": username,
                    "password": password,
                },
            )
        finally:
            del password

        parser = PageText()
        parser.feed(page)

        if (
            urllib.parse.urlsplit(final).path
            != "/en-us/user/home/"
            or "User Information" not in parser.text
        ):
            print("Login was not confirmed.")
            return False

        match = re.search(
            r"\bWelcome\s+([\w.\-@]+)",
            parser.text,
        )

        identified = match.group(1) if match else None

        if identified and identified.lower() != username.lower():
            print("ERROR: Account identity mismatch.")
            return False

        self.account = identified or username

        print("Web login confirmed:", self.account)
        if _saved_user is None:
            _sh_offer(username, getattr(self, "_login_password", None))
        return True

    def home(self):
        _, page = self.request(HOME)

        parser = PageText()
        parser.feed(page)

        if "User Information" not in parser.text:
            raise RuntimeError("Login required")

        return parser.text

    def quota(self):
        if not self.login():
            return

        url = BASE + "/en-us/user/get_user_metadata/"
        _, raw = self.request(url, ajax=True)

        try:
            payload = json.loads(raw)
            result = payload.get("result", {})

            if not isinstance(result, dict):
                raise ValueError("Invalid metadata format")

            profiles = [
                v for v in result.values()
                if isinstance(v, dict)
            ]

            profile = next(
                (
                    v for v in profiles
                    if v.get("normal_username", "").lower()
                    == self.account.lower()
                ),
                None,
            )

            if profile is None:
                raise ValueError("Account metadata not found")

            credit_mb = float(profile["credit"])

        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            print("ERROR: Could not read account metadata.")
            return

        print("\n========== SHARIF QUOTA ==========")
        print("Sharif ID:", profile.get("normal_username"))
        print(f"Remaining Volume: {credit_mb / 1024:.3f} GB")
        print("Creation Date:", profile.get("creation_date") or "Unknown")
        print("Expiration Date:", profile.get("exp_date") or "Not specified")

    def get_sessions(self):
        if not self.login():
            return None

        _, raw = self.request(SESSIONS, ajax=True)

        try:
            obj = json.loads(raw)

            if isinstance(obj, str):
                obj = json.loads(obj)

        except (ValueError, TypeError):
            print("Session API returned an unknown format.")
            return None

        result = []

        def visit(item):
            if isinstance(item, dict):
                if "session_ip" in item:
                    result.append(item)

                for value in item.values():
                    visit(value)

            elif isinstance(item, list):
                for value in item:
                    visit(value)

        visit(obj)
        return result


def local_ip():
    try:
        p = subprocess.run(
            ["ip", "-4", "route", "get", "1.1.1.1"],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )

        match = re.search(
            r"\bsrc\s+(\d+(?:\.\d+){3})",
            p.stdout,
        )

        return match.group(1) if match else "Unknown"

    except (OSError, subprocess.SubprocessError):
        return "Unknown"


def internet_reachable():
    req = urllib.request.Request(
        "https://example.com/",
        headers={"User-Agent": "sharif-net/1.0"},
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    try:
        with opener.open(req, timeout=6) as response:
            return 200 <= response.status < 400

    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def status(client):
    ip = local_ip()

    print("\n========== CONNECTION STATUS ==========")
    print("Server IP:", ip)

    reachable = internet_reachable()

    print(
        "External HTTPS:",
        "Reachable" if reachable else "Not reachable / unknown",
    )

    if not client.account:
        print("Sharif internet owner: Unknown")
        print("Login to check your own account sessions.")
        return

    sessions = client.get_sessions()

    if sessions is None:
        print("Session information unavailable.")
        return

    ours = [
        s for s in sessions
        if s.get("session_ip") == ip
    ]

    print("Authenticated Sharif ID:", client.account)
    print("Sessions for this ID:", len(sessions))

    for session in sessions:
        print(
            " -",
            session.get("session_ip", "?"),
            session.get("session_start_time", ""),
        )

    if ours:
        print(
            "Confirmed: this Sharif account has "
            "a session on the server IP."
        )
    else:
        print("This account has no session on the server IP.")
        print("Internet owner: UNKNOWN")


def connect(client):
    if not client.login():
        return

    ip = local_ip()
    sessions = client.get_sessions()

    if sessions is not None:
        for session in sessions:
            if session.get("session_ip") == ip:
                print("This account is already connected here.")
                return

    print("\nWARNING:")
    print("Internet access is shared by all server users.")
    print("Connecting may affect another user's session.")

    confirmation = input(
        "Type CONNECT to continue: "
    ).strip()

    if confirmation != "CONNECT":
        print("Cancelled.")
        return

    password = getpass.getpass(
        "Sharif password (not saved): "
    )

    try:
        _, response = client.request(
            CONNECT,
            {
                "user": client.account,
                "pass": password,
            },
            ajax=True,
        )
    finally:
        del password

    print("Connection request submitted.")

    sessions = client.get_sessions()

    if sessions is None:
        print("Could not verify the connection.")
        return

    if any(s.get("session_ip") == ip for s in sessions):
        print("Connection confirmed for:", client.account)
    else:
        print("Connection was NOT confirmed.")


def disconnect(client):
    if not client.login():
        return

    ip = local_ip()
    sessions = client.get_sessions()

    if sessions is None:
        print("Cannot verify ownership.")
        print("Disconnect refused.")
        return

    if not any(
        s.get("session_ip") == ip for s in sessions
    ):
        print("This account does not own a reported")
        print("session on the server IP.")
        print("Disconnect refused.")
        return

    print("\nWARNING:")
    print("Disconnecting may stop internet access")
    print("for ALL Linux users on this server.")

    confirmation = input(
        "Type DISCONNECT to continue: "
    ).strip()

    if confirmation != "DISCONNECT":
        print("Cancelled.")
        return

    password = getpass.getpass(
        "Sharif password (not saved): "
    )

    try:
        client.request(
            DISCONNECT,
            {
                "user": client.account,
                "pass": password,
            },
            ajax=True,
        )
    finally:
        del password

    import time

    for attempt in range(6):
        sessions = client.get_sessions()

        if sessions is not None and not any(
            s.get("session_ip") == ip for s in sessions
        ):
            print("Session disconnected successfully.")
            return

        if attempt < 5:
            time.sleep(2)

    print("Disconnect requested; verification pending.")
    print("Check connection status again shortly.")


def main():
    if not sys.stdin.isatty():
        print(
            "Run sharif-net in an interactive terminal.",
            file=sys.stderr,
        )
        return 1

    client = Sharif()

    while True:
        print("\n========== SHARIF INTERNET ==========")
        print("1. Connect with my Sharif ID")
        print("2. Connection status / possible owner")
        print("3. My remaining quota and sessions")
        print("4. Disconnect my connection")
        print("5. Exit")

        try:
            choice = input("\nSelect: ").strip()

            if choice == "1":
                connect(client)

            elif choice == "2":
                status(client)

            elif choice == "3":
                client.quota()

                if client.account:
                    status(client)

            elif choice == "4":
                disconnect(client)

            elif choice in ("5", ""):
                return 0

            else:
                print("Invalid option.")

        except (EOFError, KeyboardInterrupt):
            print("\nExit.")
            return 0

        except (
            urllib.error.URLError,
            RuntimeError,
            ValueError,
            OSError,
        ) as exc:
            print(
                "Portal/network request failed:",
                type(exc).__name__,
            )


if __name__ == "__main__":
    sys.exit(main())
