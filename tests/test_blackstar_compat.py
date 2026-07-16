from __future__ import annotations

from dataclasses import replace

import pytest

from blackstar_compat import (
    BLACKSTAR_FAMILY_ID,
    BlackstarCompatibilityError,
    require_blackstar_compatibility,
)
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
