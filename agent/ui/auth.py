"""Local UI authentication and run ownership helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Response, abort, redirect, request, session, url_for

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    role: str
    permissions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "permissions": list(self.permissions),
        }


class AuthError(ValueError):
    pass


class LocalAuthStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema": "ui_users.v1", "users": []}
        if not isinstance(raw, dict):
            return {"schema": "ui_users.v1", "users": []}
        users = raw.get("users") if isinstance(raw.get("users"), list) else []
        return {"schema": "ui_users.v1", "users": [u for u in users if isinstance(u, dict)]}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def has_users(self) -> bool:
        return bool(self._load()["users"])

    def users(self) -> list[AuthUser]:
        out: list[AuthUser] = []
        for row in self._load()["users"]:
            out.append(
                AuthUser(
                    id=str(row.get("id", "")),
                    username=str(row.get("username", "")),
                    role=str(row.get("role", "user")),
                    permissions=tuple(str(x) for x in row.get("permissions", []) if str(x)),
                )
            )
        return out

    def get_user(self, user_id: str) -> AuthUser | None:
        for row in self._load()["users"]:
            if str(row.get("id", "")) == user_id:
                return AuthUser(
                    id=str(row.get("id", "")),
                    username=str(row.get("username", "")),
                    role=str(row.get("role", "user")),
                    permissions=tuple(str(x) for x in row.get("permissions", []) if str(x)),
                )
        return None

    def get_user_by_username(self, username: str) -> AuthUser | None:
        wanted = username.strip().lower()
        for user in self.users():
            if user.username.lower() == wanted:
                return user
        return None

    def register(self, username: str, password: str) -> AuthUser:
        username = username.strip()
        if not USERNAME_RE.fullmatch(username):
            raise AuthError("用户名需为 3-32 位字母、数字、点、横线或下划线")
        if len(password) < 8:
            raise AuthError("密码至少 8 位")
        data = self._load()
        if any(str(row.get("username", "")).lower() == username.lower() for row in data["users"]):
            raise AuthError("用户名已存在")
        first_user = not data["users"]
        salt = secrets.token_hex(16)
        user_id = secrets.token_hex(12)
        data["users"].append(
            {
                "id": user_id,
                "username": username,
                "role": "admin" if first_user else "user",
                "permissions": _default_permissions(admin=first_user),
                "salt": salt,
                "password_hash": _password_hash(password, salt),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        self._save(data)
        user = self.get_user(user_id)
        if not user:
            raise AuthError("用户创建失败")
        return user

    def verify(self, username: str, password: str) -> AuthUser | None:
        wanted = username.strip().lower()
        for row in self._load()["users"]:
            if str(row.get("username", "")).lower() != wanted:
                continue
            salt = str(row.get("salt", ""))
            expected = str(row.get("password_hash", ""))
            actual = _password_hash(password, salt)
            if hmac.compare_digest(expected, actual):
                return AuthUser(
                    id=str(row.get("id", "")),
                    username=str(row.get("username", "")),
                    role=str(row.get("role", "user")),
                    permissions=tuple(str(x) for x in row.get("permissions", []) if str(x)),
                )
        return None


def _default_permissions(*, admin: bool) -> list[str]:
    base = ["run:create", "run:read", "run:improve", "run:download", "solution:read"]
    if admin:
        base.extend(["admin:users", "chain:registry", "training:prepare", "crawler:profile"])
    return base


def _password_hash(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex()


def current_user(store: LocalAuthStore) -> AuthUser | None:
    user_id = str(session.get("user_id", "") or "")
    if not user_id:
        return None
    return store.get_user(user_id)


def sign_in(user: AuthUser) -> None:
    session.clear()
    session["user_id"] = user.id
    session["username"] = user.username


def sign_out() -> None:
    session.clear()


def login_required(store_getter: Callable[[], LocalAuthStore]):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            store = store_getter()
            if current_user(store):
                return fn(*args, **kwargs)
            return redirect(url_for("login", next=request.path))

        return wrapper

    return decorator


def require_permission(user: AuthUser | None, permission: str) -> None:
    if not user:
        abort(401)
    if user.role == "admin" or permission in user.permissions:
        return
    abort(403)


def can_access_run(meta: dict[str, str], user: AuthUser | None) -> bool:
    if not user:
        return False
    owner = str(meta.get("owner_user_id", "") or "")
    if not owner:
        return user.role == "admin"
    return owner == user.id or user.role == "admin"
