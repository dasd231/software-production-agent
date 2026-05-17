from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from agent.ui.auth import LocalAuthStore, can_access_run


def test_local_auth_store_registers_first_user_as_admin(tmp_path: Path) -> None:
    store = LocalAuthStore(tmp_path / ".agent_users.json")

    user = store.register("admin", "adminpass123")
    verified = store.verify("admin", "adminpass123")

    assert user.role == "admin"
    assert verified is not None
    assert verified.id == user.id
    assert "run:create" in verified.permissions


def test_local_auth_store_rejects_duplicate_user(tmp_path: Path) -> None:
    store = LocalAuthStore(tmp_path / ".agent_users.json")
    store.register("admin", "adminpass123")

    with pytest.raises(ValueError):
        store.register("admin", "anotherpass123")


def test_can_access_run_by_owner_or_admin(tmp_path: Path) -> None:
    store = LocalAuthStore(tmp_path / ".agent_users.json")
    admin = store.register("admin", "adminpass123")
    user = store.register("worker", "workerpass123")

    assert can_access_run({"owner_user_id": user.id}, user) is True
    assert can_access_run({"owner_user_id": user.id}, admin) is True
    assert can_access_run({"owner_user_id": "other"}, user) is False
