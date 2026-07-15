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


def test_unknown_schema_is_read_only(fixture_save_path) -> None:
    save = load_save_file(str(fixture_save_path))
    identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    unknown = replace(identity, schema_sha256="0" * 64)
    with pytest.raises(UnknownSaveSchemaError, match="schema_sha256"):
        require_supported_identity(unknown, load_profiles())
