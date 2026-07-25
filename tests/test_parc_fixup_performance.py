from __future__ import annotations

import ast
import inspect
import struct
import textwrap
from types import ModuleType

import pytest

from CrimsonGameMods import parc_serializer as mods_serializer
from CrimsonSaveEditor import parc_serializer as editor_serializer


SENTINEL = b"\xFF" * 8
SERIALIZERS = (editor_serializer, mods_serializer)


def _legacy_fixup(
    out: bytearray,
    old_parc,
    new_toc_entries: list,
) -> None:
    shifted_blocks = []
    for i, new_entry in enumerate(new_toc_entries):
        old_entry = old_parc.toc_entries[i]
        d = new_entry.data_offset - old_entry.data_offset
        if d != 0:
            shifted_blocks.append((new_entry.data_offset,
                                    new_entry.data_offset + new_entry.data_size, d))

    if not shifted_blocks:
        return

    delta_set = set(d for _, _, d in shifted_blocks)
    if len(delta_set) != 1:
        return
    delta = delta_set.pop()

    type_indices = set(old_parc.type_by_index.keys())

    sentinel = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'

    for block_start, block_end, _ in shifted_blocks:
        pos = block_start
        while pos < block_end - 12:
            if out[pos:pos + 8] != sentinel:
                pos += 1
                continue

            ref_pos = pos + 8
            if ref_pos + 4 > block_end:
                pos += 1
                continue

            old_ref = struct.unpack_from('<I', out, ref_pos)[0]

            expected_old_ref = (pos - delta) + 12
            if old_ref == expected_old_ref:
                new_ref = old_ref + delta
                struct.pack_into('<I', out, ref_pos, new_ref)
                pos += 12
                continue

            found_valid = False
            for mbc in (1, 2, 3, 4, 8):
                loc_start = pos - (mbc + 5)
                if loc_start < block_start:
                    continue
                mbc_read = struct.unpack_from('<H', out, loc_start)[0]
                if mbc_read != mbc:
                    continue
                type_idx_pos = loc_start + 2 + mbc
                if type_idx_pos + 3 > pos:
                    continue
                type_idx = struct.unpack_from('<H', out, type_idx_pos)[0]
                if type_idx not in type_indices:
                    continue
                reserved = out[type_idx_pos + 2]
                if reserved != 0:
                    continue
                new_ref = old_ref + delta
                struct.pack_into('<I', out, ref_pos, new_ref)
                found_valid = True
                break

            pos += 12 if found_valid else 1


def _put_reference(out: bytearray, pos: int, old_ref: int) -> None:
    out[pos:pos + 8] = SENTINEL
    struct.pack_into("<I", out, pos + 8, old_ref)


def _put_typed_reference(
    out: bytearray,
    pos: int,
    mask_byte_count: int,
    old_ref: int,
    *,
    type_index: int = 3,
    reserved: int = 0,
) -> None:
    loc_start = pos - (mask_byte_count + 5)
    struct.pack_into("<H", out, loc_start, mask_byte_count)
    out[loc_start + 2:loc_start + 2 + mask_byte_count] = (
        bytes([0x10 + mask_byte_count]) * mask_byte_count
    )
    type_idx_pos = loc_start + 2 + mask_byte_count
    struct.pack_into("<H", out, type_idx_pos, type_index)
    out[type_idx_pos + 2] = reserved
    _put_reference(out, pos, old_ref)


def _case(
    name: str,
    out: bytearray,
    old_blocks: tuple[tuple[int, int], ...],
    new_blocks: tuple[tuple[int, int], ...],
    expected_refs: tuple[tuple[int, int], ...] = (),
):
    expected = bytearray(out)
    for ref_pos, new_ref in expected_refs:
        struct.pack_into("<I", expected, ref_pos, new_ref)
    return pytest.param(
        {
            "out": bytes(out),
            "old_blocks": old_blocks,
            "new_blocks": new_blocks,
            "expected": bytes(expected),
        },
        id=name,
    )


def _cases():
    cases = []

    no_shift = bytearray([0xA5] * 160)
    _put_reference(no_shift, 40, 52)
    cases.append(_case(
        "no-shifted-blocks",
        no_shift,
        ((20, 100),),
        ((20, 100),),
    ))

    mixed = bytearray([0xA5] * 220)
    _put_reference(mixed, 35, 42)
    _put_reference(mixed, 126, 132)
    cases.append(_case(
        "mixed-deltas",
        mixed,
        ((20, 60), (110, 60)),
        ((25, 60), (116, 60)),
    ))

    positive = bytearray([0xA5] * 180)
    _put_reference(positive, 60, 65)
    cases.append(_case(
        "positive-global-self-reference",
        positive,
        ((40, 80),),
        ((47, 80),),
        ((68, 72),),
    ))

    negative = bytearray([0xA5] * 190)
    _put_reference(negative, 90, 111)
    cases.append(_case(
        "negative-global-self-reference",
        negative,
        ((80, 80),),
        ((71, 80),),
        ((98, 102),),
    ))

    typed = bytearray([0xA5] * 270)
    typed_expected = []
    for mask_byte_count, pos in zip((1, 2, 3, 4, 8), (55, 90, 125, 160, 200)):
        old_ref = 0x1000 + pos
        _put_typed_reference(typed, pos, mask_byte_count, old_ref)
        typed_expected.append((pos + 8, old_ref + 6))
    cases.append(_case(
        "all-typed-reference-widths",
        typed,
        ((30, 210),),
        ((36, 210),),
        tuple(typed_expected),
    ))

    false_candidates = bytearray([0xA5] * 230)
    _put_reference(false_candidates, 45, 500)
    _put_typed_reference(false_candidates, 80, 5, 600)
    _put_typed_reference(false_candidates, 115, 1, 700, type_index=99)
    _put_typed_reference(false_candidates, 150, 2, 800, reserved=7)
    cases.append(_case(
        "invalid-mask-type-and-reserved-candidates",
        false_candidates,
        ((20, 180),),
        ((24, 180),),
    ))

    boundaries = bytearray([0xA5] * 240)
    _put_reference(boundaries, 55, 62)
    boundaries[80:89] = b"\xFF" * 9
    struct.pack_into("<I", boundaries, 89, 88)
    _put_reference(boundaries, 122, 129)
    _put_reference(boundaries, 188, 195)
    _put_reference(boundaries, 205, 777)
    cases.append(_case(
        "block-boundaries-and-overlapping-sentinels",
        boundaries,
        ((50, 80), (155, 40)),
        ((55, 80), (160, 40)),
        ((63, 67), (89, 93), (130, 134)),
    ))

    return cases


CASES = _cases()


def _build_inputs(module: ModuleType, case):
    type_def = module.TypeDef(index=3, name="SyntheticType", fields=[])
    old_entries = [
        module.TOCEntry(
            index=index,
            class_index=3,
            sentinel1=0,
            sentinel2=0,
            data_offset=offset,
            data_size=size,
        )
        for index, (offset, size) in enumerate(case["old_blocks"])
    ]
    new_entries = [
        module.TOCEntry(
            index=index,
            class_index=3,
            sentinel1=0,
            sentinel2=0,
            data_offset=offset,
            data_size=size,
        )
        for index, (offset, size) in enumerate(case["new_blocks"])
    ]
    old_parc = module.ParcBlob(
        raw=b"",
        header=b"",
        schema_bytes=b"",
        schema_offset=0,
        schema_end=0,
        toc_header_bytes=b"",
        toc_offset=0,
        types=[type_def],
        type_by_index={3: type_def},
        toc_entries=old_entries,
        data_start=0,
        num_root_entries=0,
        stream_size=0,
        block_raw={},
        modified_blocks={},
    )
    return old_parc, new_entries


@pytest.mark.parametrize(
    "module",
    SERIALIZERS,
    ids=("save-editor", "game-mods"),
)
@pytest.mark.parametrize("case", CASES)
def test_native_fixup_matches_legacy_exactly(module: ModuleType, case) -> None:
    old_parc, new_entries = _build_inputs(module, case)
    legacy_out = bytearray(case["out"])
    optimized_out = bytearray(case["out"])

    _legacy_fixup(legacy_out, old_parc, new_entries)
    module._fixup_global_self_references(optimized_out, old_parc, new_entries)

    assert bytes(legacy_out) == case["expected"]
    assert bytes(optimized_out) == bytes(legacy_out)


def _function_ast(function) -> ast.FunctionDef:
    source = textwrap.dedent(inspect.getsource(function))
    parsed = ast.parse(source).body[0]
    assert isinstance(parsed, ast.FunctionDef)
    return parsed


def _fixup_ast(module: ModuleType) -> str:
    return ast.dump(
        _function_ast(module._fixup_global_self_references),
        include_attributes=False,
    )


def _assert_bounded_find_ast(function) -> None:
    find_calls = [
        node
        for node in ast.walk(_function_ast(function))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "find"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "out"
        )
    ]
    assert find_calls, "expected an actual out.find call"
    for call in find_calls:
        assert len(call.args) == 3, (
            "out.find must receive needle, start, and end"
        )
        assert not call.keywords, "out.find must use positional bounds"
        needle, start, end = call.args
        assert isinstance(needle, ast.Name) and needle.id == "sentinel"
        assert isinstance(start, ast.Name) and start.id == "pos"
        assert (
            isinstance(end, ast.BinOp)
            and isinstance(end.left, ast.Name)
            and end.left.id == "block_end"
            and isinstance(end.op, ast.Sub)
            and isinstance(end.right, ast.Constant)
            and end.right.value == 5
        ), "out.find end must be block_end - 5"


_MISSING_FIND_ARG = object()


class _RecordingBytearray(bytearray):
    def __init__(self, initial: bytes | bytearray):
        super().__init__(initial)
        self.find_calls = []

    def find(
        self,
        needle,
        start=_MISSING_FIND_ARG,
        end=_MISSING_FIND_ARG,
    ):
        self.find_calls.append((needle, start, end))
        if start is _MISSING_FIND_ARG:
            return super().find(needle)
        if end is _MISSING_FIND_ARG:
            return super().find(needle, start)
        return super().find(needle, start, end)


def _assert_bounded_runtime_calls(
    calls,
    *,
    expected_starts: tuple[int, ...],
    expected_end: int,
) -> None:
    assert len(calls) == len(expected_starts)
    for (needle, start, end), expected_start in zip(calls, expected_starts):
        assert needle == SENTINEL
        assert start is not _MISSING_FIND_ARG, (
            "find must receive an explicit start"
        )
        assert end is not _MISSING_FIND_ARG, (
            "find must receive an explicit end"
        )
        assert start == expected_start
        assert end == expected_end


def _unbounded_find_surrogate(out, sentinel, pos, block_end):
    del pos, block_end
    return out.find(sentinel)


def test_fixup_implementations_keep_equivalent_ast_bodies() -> None:
    assert _fixup_ast(editor_serializer) == _fixup_ast(mods_serializer)


@pytest.mark.parametrize(
    "module",
    SERIALIZERS,
    ids=("save-editor", "game-mods"),
)
def test_fixup_ast_requires_explicit_per_block_find_bounds(
    module: ModuleType,
) -> None:
    _assert_bounded_find_ast(module._fixup_global_self_references)


def test_ast_contract_rejects_unbounded_find_surrogate() -> None:
    with pytest.raises(
        AssertionError,
        match="needle, start, and end",
    ):
        _assert_bounded_find_ast(_unbounded_find_surrogate)


@pytest.mark.parametrize(
    "module",
    SERIALIZERS,
    ids=("save-editor", "game-mods"),
)
def test_fixup_runtime_find_stays_within_shifted_block(
    module: ModuleType,
) -> None:
    raw = bytearray([0xA5] * 140)
    _put_reference(raw, 70, 77)
    case = {
        "old_blocks": ((20, 40),),
        "new_blocks": ((25, 40),),
    }
    old_parc, new_entries = _build_inputs(module, case)
    legacy_out = bytearray(raw)
    recorded_out = _RecordingBytearray(raw)

    _legacy_fixup(legacy_out, old_parc, new_entries)
    module._fixup_global_self_references(
        recorded_out,
        old_parc,
        new_entries,
    )

    assert bytes(recorded_out) == bytes(legacy_out)
    assert struct.unpack_from("<I", recorded_out, 78)[0] == 77
    _assert_bounded_runtime_calls(
        recorded_out.find_calls,
        expected_starts=(25,),
        expected_end=60,
    )


@pytest.mark.parametrize(
    "module",
    SERIALIZERS,
    ids=("save-editor", "game-mods"),
)
def test_fixup_runtime_reuses_bound_after_false_candidate(
    module: ModuleType,
) -> None:
    raw = bytearray([0xA5] * 160)
    _put_reference(raw, 40, 500)
    _put_reference(raw, 110, 117)
    case = {
        "old_blocks": ((20, 80),),
        "new_blocks": ((25, 80),),
    }
    old_parc, new_entries = _build_inputs(module, case)
    legacy_out = bytearray(raw)
    recorded_out = _RecordingBytearray(raw)

    _legacy_fixup(legacy_out, old_parc, new_entries)
    module._fixup_global_self_references(
        recorded_out,
        old_parc,
        new_entries,
    )

    assert bytes(recorded_out) == bytes(legacy_out)
    _assert_bounded_runtime_calls(
        recorded_out.find_calls,
        expected_starts=(25, 41),
        expected_end=100,
    )


def test_runtime_contract_rejects_unbounded_find_surrogate() -> None:
    recorded_out = _RecordingBytearray(b"\xA5" * 32 + SENTINEL)
    _unbounded_find_surrogate(recorded_out, SENTINEL, 0, 32)
    with pytest.raises(AssertionError, match="explicit start"):
        _assert_bounded_runtime_calls(
            recorded_out.find_calls,
            expected_starts=(0,),
            expected_end=27,
        )


def test_fixup_source_has_no_bytewise_sentinel_comparison() -> None:
    for module in SERIALIZERS:
        source = inspect.getsource(module._fixup_global_self_references)
        assert "out[pos:pos + 8] != sentinel" not in source
