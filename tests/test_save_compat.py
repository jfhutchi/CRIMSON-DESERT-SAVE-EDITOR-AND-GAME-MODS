from dataclasses import replace

import pytest

from save_compat import (
    UnknownSaveSchemaError,
    compute_schema_identity,
    load_profiles,
    match_profile,
    require_supported_identity,
)
from save_crypto import load_save_file


def test_copied_fixture_matches_committed_profile(fixture_save_path) -> None:
    save = load_save_file(str(fixture_save_path))
    assert save.is_schema_supported
    assert save.compatibility_profile_id == "fixture-current-20260714"
    identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    profile = match_profile(identity, load_profiles())
    assert profile is not None
    assert profile.profile_id == "fixture-current-20260714"


def test_community_patch_profile_is_enrolled() -> None:
    profiles = load_profiles()
    by_id = {p.profile_id: p for p in profiles}
    assert "community-2026-07-patch" in by_id, (
        "current-patch saves must stay writable; enrolled from a player save "
        "after verifying a byte-identical serialize/reload round-trip"
    )
    community = by_id["community-2026-07-patch"]
    fixture = by_id["fixture-current-20260714"]
    assert community.identity.schema_sha256 != fixture.identity.schema_sha256
    assert community.identity.container_version == 2
    assert community.knowledge_element_mask_hex in (
        community.identity.observed_encodings[
            "KnowledgeSaveData._list.element_mask"
        ].split(",")
    )


def test_unknown_schema_is_read_only(fixture_save_path) -> None:
    save = load_save_file(str(fixture_save_path))
    identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    unknown = replace(identity, schema_sha256="0" * 64)
    with pytest.raises(UnknownSaveSchemaError, match="schema_sha256"):
        require_supported_identity(unknown, load_profiles())
