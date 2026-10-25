"""Concurrent key creation must preserve the unique-name API contract."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.api.api_keys import CreateApiKeyRequest, create_key
from app.models import ApiKey


def test_key_created_after_duplicate_check_returns_conflict(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/keys.db')
    SQLModel.metadata.create_all(engine)

    def concurrent_creation():
        with Session(engine) as other:
            other.add(ApiKey(name='Integration', prefix='prefix', key_hash='hash'))
            other.commit()
        return 'test-secret', 'prefix2', 'hash2'

    with Session(engine) as session, patch('app.api.api_keys.generate_key', side_effect=concurrent_creation):
        with pytest.raises(HTTPException) as exc:
            create_key(CreateApiKeyRequest(name='Integration'), session)
        assert exc.value.status_code == 409
        # The failed request must leave a usable rolled-back session.
        assert session.get(ApiKey, 1).key_hash == 'hash'
    engine.dispose()
