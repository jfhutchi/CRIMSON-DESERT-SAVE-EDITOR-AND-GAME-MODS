from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragon_wheel_deploy import (
    MARKER_NAME,
    DragonWheelDeploymentError,
    deploy_dragon_wheel,
    restore_dragon_wheel,
)
from dragon_wheel_patch import DragonWheelPatchResult, DragonWheelReport


class FakeCoordinator:
    def __init__(self, *, fail_post_write: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_post_write = fail_post_write

    def pre_write(self, game_path: str, group: str, owner: str):
        self.calls.append(("pre_write", group))
        return True, "OK"

    def post_write(
        self,
        game_path: str,
        group: str,
        content: str,
        files: list[str],
        owner: str,
    ) -> None:
        self.calls.append(("post_write", group))
        if self.fail_post_write:
            raise RuntimeError("coordinator state failure")

    def pre_restore(self, game_path: str, group: str, owner: str):
        self.calls.append(("pre_restore", group))
        return True, "OK"

    def post_restore(self, game_path: str, group: str) -> None:
        self.calls.append(("post_restore", group))


class FakeCrimsonRs:
    Compression = SimpleNamespace(NONE=0)
    Crypto = SimpleNamespace(NONE=0)

    class PackGroupBuilder:
        def __init__(self, output_dir: str, compression: int, crypto: int) -> None:
            self.output_dir = Path(output_dir)
            self.files: list[tuple[str, str, bytes]] = []

        def add_file(self, directory: str, name: str, data: bytes) -> None:
            self.files.append((directory, name, bytes(data)))

        def finish(self) -> bytes:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            payload = b"|".join(
                directory.encode("ascii") + b"/" + name.encode("ascii") + b":" + data
                for directory, name, data in self.files
            )
            pamt = b"fake-pamt"
            (self.output_dir / "0.paz").write_bytes(payload)
            (self.output_dir / "0.pamt").write_bytes(pamt)
            return pamt

    def __init__(self, *, fail_temp_write: bool = False) -> None:
        self.fail_temp_write = fail_temp_write

    @staticmethod
    def parse_pamt_bytes(data: bytes) -> dict[str, int]:
        assert data == b"fake-pamt"
        return {"checksum": 0xD06A}

    @staticmethod
    def parse_papgt_file(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def add_papgt_entry(
        document: dict,
        group: str,
        checksum: int,
        is_optional: int,
        language: int,
    ) -> dict:
        result = dict(document)
        result["entries"] = list(document.get("entries", [])) + [{
            "group_name": group,
            "pack_meta_checksum": checksum,
            "is_optional": is_optional,
            "language": language,
        }]
        return result

    def write_papgt_file(self, document: dict, path: str) -> None:
        if self.fail_temp_write and ".dragon-wheel-" in Path(path).name:
            raise OSError("simulated PAPGT write failure")
        Path(path).write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _patch_result() -> DragonWheelPatchResult:
    pabgh = b"patched-header"
    pabgb = b"patched-body"
    report = DragonWheelReport(
        schema_id="synthetic-current",
        state="patched",
        source_pabgh_sha256=_sha(b"original-header"),
        source_pabgb_sha256=_sha(b"original-body"),
        output_pabgh_sha256=_sha(pabgh),
        output_pabgb_sha256=_sha(pabgb),
        before_categories=(0x4E, 0x51),
        after_categories=(0x4E, 0x4F, 0x51),
        adjusted_entry_indexes=(27, 28, 29),
        byte_growth=1,
        already_enabled=False,
    )
    return DragonWheelPatchResult(pabgh=pabgh, pabgb=pabgb, report=report)


def _make_game_tree(tmp_path: Path, groups: list[str]) -> Path:
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    entries = []
    for group in groups:
        entries.append({"group_name": group, "pack_meta_checksum": int(group)})
        overlay = game / group
        overlay.mkdir()
        (overlay / "0.paz").write_bytes(f"paz-{group}".encode("ascii"))
        (overlay / "0.pamt").write_bytes(f"pamt-{group}".encode("ascii"))
    (game / "meta" / "0.papgt").write_text(
        json.dumps({"version": 7, "entries": entries}, sort_keys=True),
        encoding="utf-8",
    )
    return game


def _groups(game: Path, crimson_rs: FakeCrimsonRs) -> tuple[str, ...]:
    doc = crimson_rs.parse_papgt_file(str(game / "meta" / "0.papgt"))
    return tuple(entry["group_name"] for entry in doc["entries"])


def test_apply_creates_backup_marker_and_preserves_papgt(tmp_path: Path) -> None:
    crimson_rs = FakeCrimsonRs()
    coordinator = FakeCoordinator()
    game = _make_game_tree(tmp_path, groups=["0008", "0042"])
    original_papgt = (game / "meta" / "0.papgt").read_bytes()

    receipt = deploy_dragon_wheel(
        game_path=game,
        overlay_group="0066",
        patch_result=_patch_result(),
        backup_root=tmp_path / "backups",
        crimson_rs_module=crimson_rs,
        timestamp="20260715-210000",
        coordinator_module=coordinator,
    )

    assert receipt.backup_dir == tmp_path / "backups" / "20260715-210000"
    assert (receipt.backup_dir / "0.papgt").read_bytes() == original_papgt
    assert (game / "0066" / MARKER_NAME).is_file()
    assert _groups(game, crimson_rs) == ("0008", "0042", "0066")
    assert coordinator.calls == [("pre_write", "0066"), ("post_write", "0066")]


def test_apply_refuses_unmarked_existing_overlay(tmp_path: Path) -> None:
    game = _make_game_tree(tmp_path, groups=["0008", "0066"])

    with pytest.raises(DragonWheelDeploymentError, match="not owned"):
        deploy_dragon_wheel(
            game,
            "0066",
            _patch_result(),
            tmp_path / "backups",
            FakeCrimsonRs(),
            "20260715-210000",
            FakeCoordinator(),
        )


def test_apply_rolls_back_after_papgt_failure(tmp_path: Path) -> None:
    game = _make_game_tree(tmp_path, groups=["0008"])
    original_papgt = (game / "meta" / "0.papgt").read_bytes()

    with pytest.raises(DragonWheelDeploymentError, match="rolled back"):
        deploy_dragon_wheel(
            game,
            "0066",
            _patch_result(),
            tmp_path / "backups",
            FakeCrimsonRs(fail_temp_write=True),
            "20260715-210000",
            FakeCoordinator(),
        )

    assert (game / "meta" / "0.papgt").read_bytes() == original_papgt
    assert not (game / "0066").exists()


def test_apply_restores_owned_overlay_when_post_write_fails(tmp_path: Path) -> None:
    game = _make_game_tree(tmp_path, groups=["0008", "0066"])
    marker = game / "0066" / MARKER_NAME
    marker.write_text("old-marker", encoding="utf-8")
    original_overlay = {
        path.name: path.read_bytes() for path in (game / "0066").iterdir()
    }
    original_papgt = (game / "meta" / "0.papgt").read_bytes()

    with pytest.raises(DragonWheelDeploymentError, match="rolled back"):
        deploy_dragon_wheel(
            game,
            "0066",
            _patch_result(),
            tmp_path / "backups",
            FakeCrimsonRs(),
            "20260715-210000",
            FakeCoordinator(fail_post_write=True),
        )

    assert (game / "meta" / "0.papgt").read_bytes() == original_papgt
    assert {
        path.name: path.read_bytes() for path in (game / "0066").iterdir()
    } == original_overlay


def test_restore_removes_only_owned_overlay_and_preserves_groups(tmp_path: Path) -> None:
    crimson_rs = FakeCrimsonRs()
    coordinator = FakeCoordinator()
    game = _make_game_tree(tmp_path, groups=["0008", "0042", "0066"])
    (game / "0066" / MARKER_NAME).write_text("owned", encoding="utf-8")

    remaining = restore_dragon_wheel(
        game,
        "0066",
        crimson_rs,
        coordinator_module=coordinator,
    )

    assert remaining == ("0008", "0042")
    assert not (game / "0066").exists()
    assert (game / "0042" / "0.paz").is_file()
    assert _groups(game, crimson_rs) == ("0008", "0042")
    assert coordinator.calls == [("pre_restore", "0066"), ("post_restore", "0066")]


def test_restore_refuses_foreign_overlay(tmp_path: Path) -> None:
    game = _make_game_tree(tmp_path, groups=["0008", "0066"])

    with pytest.raises(DragonWheelDeploymentError, match="ownership marker"):
        restore_dragon_wheel(game, "0066", FakeCrimsonRs(), FakeCoordinator())
