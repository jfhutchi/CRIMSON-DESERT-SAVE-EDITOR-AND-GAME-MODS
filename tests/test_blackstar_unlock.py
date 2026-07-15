from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import blackstar_unlock
from blackstar_unlock import (
    BLACKSTAR_CHARACTER_KEY,
    BLACKSTAR_KNOWLEDGE_KEYS,
    BLACKSTAR_MOUNT_TEMPLATE,
    BLACKSTAR_SPEC,
    BlackstarSpec,
    BlackstarValidationError,
    apply_blackstar_plan,
    build_blackstar_plan,
    canonical_quest_snapshot,
    unlock_blackstar,
)
from parc_inserter3 import build_insert_context
from save_compat import load_profiles, require_supported_identity
from save_crypto import load_save_file


@pytest.fixture(scope="module")
def blackstar_fixture(fixture_save_path: Path):
    save = load_save_file(str(fixture_save_path))
    profile = require_supported_identity(save.schema_identity, load_profiles())
    return bytes(save.decompressed_blob), profile


def test_dry_run_reports_exact_changes_without_mutating_input(blackstar_fixture) -> None:
    blob, profile = blackstar_fixture
    mutable_input = bytearray(blob)
    before = bytes(mutable_input)
    events = []

    result = unlock_blackstar(
        blob=mutable_input,
        profile=profile,
        dry_run=True,
        operation_id="test-blackstar-dry-run",
        progress=events.append,
    )

    assert result.output_blob is None
    assert result.candidate_sha256 != result.input_sha256
    assert result.report.mount_before == 0
    assert result.report.mount_after == 1
    assert result.report.knowledge_added
    assert result.report.quest_changes == 0
    assert bytes(mutable_input) == before
    assert [event.completed for event in events] == sorted(
        event.completed for event in events
    )
    assert events[-1].phase == "complete"


@pytest.fixture(scope="module")
def applied_blackstar(blackstar_fixture):
    blob, profile = blackstar_fixture
    return unlock_blackstar(
        blob=blob,
        profile=profile,
        dry_run=False,
        operation_id="test-blackstar-apply",
    )


def test_first_run_changes_only_mount_and_requested_knowledge(
    blackstar_fixture,
    applied_blackstar,
) -> None:
    blob, _profile = blackstar_fixture
    assert applied_blackstar.output_blob is not None
    assert applied_blackstar.report.mount_before == 0
    assert applied_blackstar.report.mount_after == 1
    assert set(applied_blackstar.report.knowledge_added).issubset(BLACKSTAR_KNOWLEDGE_KEYS)
    assert (
        len(applied_blackstar.report.knowledge_added)
        + len(applied_blackstar.report.knowledge_skipped)
        == len(BLACKSTAR_KNOWLEDGE_KEYS)
    )
    assert applied_blackstar.report.quest_changes == 0
    assert canonical_quest_snapshot(build_insert_context(blob)) == canonical_quest_snapshot(
        build_insert_context(applied_blackstar.output_blob)
    )


def test_second_run_is_byte_identical(blackstar_fixture, applied_blackstar) -> None:
    _blob, profile = blackstar_fixture
    first = applied_blackstar.output_blob
    assert first is not None
    second = unlock_blackstar(
        blob=first,
        profile=profile,
        dry_run=False,
        operation_id="test-blackstar-second-run",
    )
    assert second.output_blob == first
    assert second.candidate_sha256 == applied_blackstar.candidate_sha256
    assert second.report.byte_growth == 0
    assert second.report.knowledge_added == ()


def test_mount_present_knowledge_missing_is_repaired(blackstar_fixture) -> None:
    blob, profile = blackstar_fixture
    mount_only = unlock_blackstar(
        blob=blob,
        profile=profile,
        dry_run=False,
        operation_id="test-blackstar-mount-only",
        spec=BlackstarSpec(
            character_key=BLACKSTAR_CHARACTER_KEY,
            mount_template=BLACKSTAR_MOUNT_TEMPLATE,
            knowledge_keys=(),
        ),
    )
    assert mount_only.output_blob is not None
    repaired = unlock_blackstar(
        blob=mount_only.output_blob,
        profile=profile,
        dry_run=False,
        operation_id="test-blackstar-repair",
    )
    assert repaired.report.mount_before == 1
    assert repaired.report.mount_after == 1
    assert repaired.report.knowledge_added


def test_duplicate_mounts_are_refused(blackstar_fixture) -> None:
    blob, profile = blackstar_fixture
    fake_target = BlackstarSpec(
        character_key=BLACKSTAR_CHARACTER_KEY + 1,
        mount_template=BLACKSTAR_MOUNT_TEMPLATE,
        knowledge_keys=(),
    )
    context = build_insert_context(blob)
    first = apply_blackstar_plan(
        context, profile, fake_target, build_blackstar_plan(context, profile, fake_target)
    )
    context = build_insert_context(first.output_blob)
    second = apply_blackstar_plan(
        context, profile, fake_target, build_blackstar_plan(context, profile, fake_target)
    )
    with pytest.raises(BlackstarValidationError, match="Blackstar mounts"):
        unlock_blackstar(
            second.output_blob,
            profile,
            dry_run=True,
            operation_id="test-blackstar-duplicate-mount",
        )


def test_duplicate_requested_knowledge_is_refused(
    blackstar_fixture,
    applied_blackstar,
) -> None:
    _blob, profile = blackstar_fixture
    context = build_insert_context(applied_blackstar.output_blob)
    plan = build_blackstar_plan(context, profile, BLACKSTAR_SPEC)
    forced = replace(plan, knowledge_missing=(BLACKSTAR_KNOWLEDGE_KEYS[0],))
    duplicate = apply_blackstar_plan(context, profile, BLACKSTAR_SPEC, forced)
    with pytest.raises(BlackstarValidationError, match="knowledge"):
        unlock_blackstar(
            duplicate.output_blob,
            profile,
            dry_run=True,
            operation_id="test-blackstar-duplicate-knowledge",
        )


def test_production_service_has_no_quest_insertion_dependency() -> None:
    source = inspect.getsource(blackstar_unlock)
    assert "insert_quest" not in source


def test_quest_snapshot_covers_every_quest_object() -> None:
    def quest(value: str):
        field = SimpleNamespace(
            field_index=0,
            name="_questStateList",
            type_name="list",
            present=True,
            value_repr=value,
            child_mask_bytes=b"",
            child_fields=None,
            list_elements=None,
        )
        return SimpleNamespace(class_name="QuestSaveData", fields=[field])

    first = SimpleNamespace(
        result={"objects": [quest("unchanged"), quest("second-before")]}
    )
    second = SimpleNamespace(
        result={"objects": [quest("unchanged"), quest("second-after")]}
    )

    assert canonical_quest_snapshot(first) != canonical_quest_snapshot(second)
