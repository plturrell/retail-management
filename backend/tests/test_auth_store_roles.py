from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.auth import dependencies as auth_deps
from app.auth.dependencies import RoleEnum


class _FakeCollectionGroup:
    def where(self, *_args, **_kwargs):
        return self

    def stream(self):
        return iter(())


class _FakeMissingRoleDoc:
    exists = False


class _FakeStoreRef:
    def __init__(self, store_id: str, roles: dict[str, dict]):
        self.id = store_id
        self._roles = roles

    def collection(self, name: str):
        assert name == "roles"
        return _FakeRoleCollection(self, self._roles)


class _FakeRoleCollection:
    def __init__(self, store_ref: _FakeStoreRef, roles: dict[str, dict]):
        self.parent = store_ref
        self._store_ref = store_ref
        self._roles = roles

    def document(self, doc_id: str):
        role = self._roles.get(doc_id)
        if role is None:
            return _FakeMissingRoleDoc()
        return _FakeRoleDoc(doc_id, role, self)


class _FakeRoleDoc:
    exists = True

    def __init__(self, doc_id: str, data: dict, collection: _FakeRoleCollection):
        self.id = doc_id
        self._data = dict(data)
        self.reference = self
        self.parent = collection

    def get(self):
        return self

    def to_dict(self):
        return dict(self._data)


class _FakeStoreDoc:
    def __init__(self, store_id: str, roles: dict[str, dict]):
        self.reference = _FakeStoreRef(store_id, roles)


class _FakeStoreCollection:
    def __init__(self, stores: list[_FakeStoreDoc]):
        self._stores = stores

    def stream(self):
        return iter(self._stores)


class _FakeFirestore:
    def __init__(self, stores: list[_FakeStoreDoc]):
        self._stores = stores

    def collection_group(self, name: str):
        assert name == "roles"
        return _FakeCollectionGroup()

    def collection(self, name: str):
        assert name == "stores"
        return _FakeStoreCollection(self._stores)


@pytest.mark.asyncio
async def test_current_user_falls_back_to_role_doc_id_when_group_query_is_empty(monkeypatch):
    user_id = str(uuid4())
    store_id = str(uuid4())
    role_id = str(uuid4())

    monkeypatch.setattr(
        auth_deps,
        "query_collection",
        lambda *_args, **_kwargs: [
            {
                "id": user_id,
                "firebase_uid": "firebase-craig",
                "email": "turrell.craig.1971@gmail.com",
                "full_name": "Craig",
                "created_at": datetime.now(timezone.utc),
            }
        ],
    )

    db = _FakeFirestore(
        [
            _FakeStoreDoc(
                store_id,
                {
                    user_id: {
                        "id": role_id,
                        "role": "owner",
                        "created_at": datetime.now(timezone.utc),
                    }
                },
            )
        ]
    )

    user = await auth_deps.get_current_user({"uid": "firebase-craig"}, db)

    assert len(user["store_roles"]) == 1
    assert str(user["store_roles"][0]["store_id"]) == store_id
    assert str(user["store_roles"][0]["user_id"]) == user_id
    assert user["store_roles"][0]["role"] == RoleEnum.owner


# The companion `test_system_admin_active_locations_are_the_five_canonical_stores`
# test is held back in `_pending_b4_stores_router_test.py.txt` until the
# stores router gains its `canonical_active_location_stores` integration
# in cluster B4.
