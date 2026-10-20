"""Local credential vault.

Two things can be remembered between sessions:

  session   the site's own browser storage state (cookies/localStorage) captured
            after a successful login — no password involved
  password  optional, only if the user ticks "remember me", encrypted with a
            Fernet key kept next to it

Both live under `data/`, both files are chmod 0600, both are deleted by
`clear()` — which is what the Log out button calls.

Threat model, stated plainly: the key sits on the same disk as the ciphertext,
so this protects against casual file reads, backups and shoulder-surfing the
dashboard — not against someone who already has your user account. That is the
inherent ceiling of "remember my password on this machine".
"""
from __future__ import annotations

import base64
import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KEY_PATH = os.path.join(DATA_DIR, ".vault.key")
BLOB_PATH = os.path.join(DATA_DIR, "vault.enc")
SESSION_PATH = os.path.join(DATA_DIR, "session.json")


def mask_email(email: str) -> str:
    if not email:
        return ""
    name, _, domain = email.partition("@")
    keep = name[:2] if len(name) > 2 else name[:1]
    return f"{keep}{'*' * max(2, len(name) - len(keep))}@{domain}"


class Vault:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._fernet = None

    # ------------------------------------------------------------------ crypto
    def _cipher(self):
        if self._fernet is not None:
            return self._fernet
        try:
            from cryptography.fernet import Fernet
        except Exception:
            return None
        if os.path.exists(KEY_PATH):
            with open(KEY_PATH, "rb") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key()
            fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
        self._fernet = Fernet(key)
        return self._fernet

    def _write_private(self, path: str, data: bytes):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

    # ------------------------------------------------------------------- blob
    def _load(self) -> dict:
        if not os.path.exists(BLOB_PATH):
            return {}
        try:
            with open(BLOB_PATH, "rb") as f:
                raw = f.read()
            c = self._cipher()
            if c is None:
                return {}
            return json.loads(c.decrypt(raw).decode("utf-8"))
        except Exception:
            return {}

    def _save(self, payload: dict):
        c = self._cipher()
        if c is None:
            raise RuntimeError("cryptography is not installed in this interpreter")
        blob = c.encrypt(json.dumps(payload).encode("utf-8"))
        self._write_private(BLOB_PATH, blob)

    # ------------------------------------------------------------------ public
    def save_login(self, email: str, password: str | None, storage_state: dict | None,
                   remember_password: bool = False):
        payload = self._load()
        payload["email"] = email or payload.get("email", "")
        payload["saved_at"] = time.time()
        if storage_state:
            payload["storage_state"] = storage_state
        if remember_password and password:
            payload["password"] = password
            payload["remember_password"] = True
        else:
            payload.pop("password", None)
            payload["remember_password"] = False
        self._save(payload)

    def save_session(self, email: str, storage_state: dict):
        payload = self._load()
        payload["email"] = email or payload.get("email", "")
        payload["storage_state"] = storage_state
        payload["saved_at"] = time.time()
        self._save(payload)

    def load(self) -> dict:
        """{email, password?, storage_state?, saved_at, remember_password}"""
        return self._load()

    def credentials(self) -> tuple[str, str] | None:
        p = self._load()
        email = p.get("email") or ""
        pw = p.get("password")
        if email and pw:
            return email, pw
        return None

    def storage_state(self) -> dict | None:
        return (self._load() or {}).get("storage_state")

    def has_any(self) -> bool:
        return bool(self._load())

    def status(self) -> dict:
        p = self._load()
        st = p.get("storage_state")
        cookies = len(st.get("cookies", [])) if isinstance(st, dict) else 0
        self._chmod()
        return {
            "saved": bool(p),
            "email_masked": mask_email(p.get("email", "")),
            "has_session": bool(cookies),
            "cookies": cookies,
            "has_password": bool(p.get("password")),
            "remember_password": bool(p.get("remember_password")),
            "saved_at": p.get("saved_at"),
            "saved_ago": (f"{int((time.time() - p['saved_at']) // 60)} min ago"
                          if p.get("saved_at") else None),
            "vault": BLOB_PATH,
            "key": KEY_PATH,
            "encrypted": os.path.exists(BLOB_PATH),
        }

    def _chmod(self):
        for path in (BLOB_PATH, KEY_PATH):
            try:
                if os.path.exists(path):
                    os.chmod(path, 0o600)
            except OSError:
                pass

    def clear(self) -> dict:
        """Delete the ciphertext *and* the key — logging out leaves nothing behind."""
        for path in (BLOB_PATH, SESSION_PATH, KEY_PATH):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        self._fernet = None
        return self.status()
