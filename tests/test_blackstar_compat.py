from __future__ import annotations

from dataclasses import replace

import pytest

import blackstar_compat
from blackstar_compat import (
    BLACKSTAR_FAMILY_ID,
    BlackstarCompatibilityError,
    require_blackstar_compatibility,
)
from blackstar_knowledge import CallDragonKnowledgeError
from parc_inserter3 import build_insert_context
from save_crypto import load_save_file


def test_early_unknown_schema_has_blackstar_scoped_compatibility(early_114_save_path) -> None:
    save = load_save_file(str(early_114_save_path))
    assert not save.is_schema_supported
    grant = require_blackstar_compatibility(
        build_insert_context(save.decompressed_blob), save.schema_identity
    )
    assert grant.family_id == BLACKSTAR_FAMILY_ID
    assert grant.source_schema_sha256 == save.schema_identity.schema_sha256


def test_changed_identity_is_refused(early_114_save_path) -> None:
    save = load_save_file(str(early_114_save_path))
    identity = replace(save.schema_identity, container_version=99)
    with pytest.raises(BlackstarCompatibilityError, match="container"):
        require_blackstar_compatibility(
            build_insert_context(save.decompressed_blob), identity
        )


def test_missing_call_dragon_requires_compatible_local_template(
    early_114_save_path,
    monkeypatch,
) -> None:
    save = load_save_file(str(early_114_save_path))

    def fail_template(_context):
        raise CallDragonKnowledgeError(
            "No compatible target-local Call Dragon template"
        )

    monkeypatch.setattr(
        blackstar_compat,
        "select_call_dragon_template",
        fail_template,
        raising=False,
    )
    with pytest.raises(BlackstarCompatibilityError, match="target-local"):
        require_blackstar_compatibility(
            build_insert_context(save.decompressed_blob), save.schema_identity
        )
