from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import parc_serializer
import save_parser

REQUIRED_TYPES = (
    "MercenaryClanSaveData",
    "MercenarySaveData",
    "ExperienceLevelSaveData",
    "FriendlyDailyCountSaveData",
    "KnowledgeSaveData",
)


@dataclass(frozen=True)
class SaveSchemaIdentity:
    container_version: int
    schema_sha256: str
    root_entry_count: int
    type_count: int
    required_type_signatures: dict[str, str]
    observed_encodings: dict[str, str]


@dataclass(frozen=True)
class CompatibilityProfile:
    profile_id: str
    identity: SaveSchemaIdentity
    mount_list_prefix: int
    mount_element_mask_hex: str
    knowledge_list_prefix: int
    knowledge_element_mask_hex: str


class UnknownSaveSchemaError(ValueError):
    pass


def _type_signature(type_def: parc_serializer.TypeDef) -> str:
    payload = [
        [field.name, field.type_name, field.meta_kind, field.meta_size, field.meta_aux]
        for field in type_def.fields
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def extract_required_list_encodings(result: dict) -> dict[str, str]:
    targets = {
        "MercenaryClanSaveData": "_mercenaryDataList",
        "KnowledgeSaveData": "_list",
    }
    encodings: dict[str, str] = {}
    objects = {obj.class_name: obj for obj in result["objects"]}
    for class_name, field_name in targets.items():
        prefix_key = f"{class_name}.{field_name}.list_prefix"
        mask_key = f"{class_name}.{field_name}.element_mask"
        obj = objects.get(class_name)
        field = (
            next((item for item in obj.fields if item.name == field_name), None)
            if obj
            else None
        )
        elements = field.list_elements if field and field.list_elements else []
        encodings[prefix_key] = str(field.list_prefix_u8) if field else "MISSING"
        encodings[mask_key] = (
            elements[-1].child_mask_bytes.hex()
            if elements and elements[-1].child_mask_bytes
            else "MISSING"
        )
    return encodings


def compute_schema_identity(blob: bytes, raw_header: bytes) -> SaveSchemaIdentity:
    parc = parc_serializer.parse_parc_blob(blob)
    result = save_parser.build_result_from_raw(blob, {"input_kind": "raw_blob"})
    by_name = {type_def.name: type_def for type_def in parc.types}
    signatures = {
        name: _type_signature(by_name[name]) if name in by_name else "MISSING"
        for name in REQUIRED_TYPES
    }
    version = struct.unpack_from("<H", raw_header, 4)[0] if len(raw_header) >= 6 else 0
    return SaveSchemaIdentity(
        container_version=version,
        schema_sha256=hashlib.sha256(parc.schema_bytes).hexdigest(),
        root_entry_count=parc.num_root_entries,
        type_count=len(parc.types),
        required_type_signatures=signatures,
        observed_encodings=extract_required_list_encodings(result),
    )


def load_profiles(path: Path | None = None) -> tuple[CompatibilityProfile, ...]:
    source = path or Path(__file__).with_name("save_schema_profiles.json")
    if not source.is_file():
        return ()
    data = json.loads(source.read_text(encoding="utf-8"))
    return tuple(
        CompatibilityProfile(
            profile_id=item["profile_id"],
            identity=SaveSchemaIdentity(**item["identity"]),
            mount_list_prefix=item["mount_list_prefix"],
            mount_element_mask_hex=item["mount_element_mask_hex"],
            knowledge_list_prefix=item["knowledge_list_prefix"],
            knowledge_element_mask_hex=item["knowledge_element_mask_hex"],
        )
        for item in data["profiles"]
    )


def match_profile(
    identity: SaveSchemaIdentity,
    profiles: tuple[CompatibilityProfile, ...],
) -> CompatibilityProfile | None:
    return next((profile for profile in profiles if profile.identity == identity), None)


def require_supported_identity(
    identity: SaveSchemaIdentity,
    profiles: tuple[CompatibilityProfile, ...],
) -> CompatibilityProfile:
    profile = match_profile(identity, profiles)
    if profile is None:
        raise UnknownSaveSchemaError(
            f"Unknown save schema: schema_sha256={identity.schema_sha256} "
            f"container_version={identity.container_version}"
        )
    return profile


def _profile_from_fixture(
    fixture: Path,
    profile_id: str,
) -> CompatibilityProfile:
    from save_crypto import load_save_file

    save = load_save_file(str(fixture))
    identity = save.schema_identity or compute_schema_identity(
        bytes(save.decompressed_blob), save.raw_header
    )
    encodings = identity.observed_encodings
    mount_prefix = encodings[
        "MercenaryClanSaveData._mercenaryDataList.list_prefix"
    ]
    mount_mask = encodings[
        "MercenaryClanSaveData._mercenaryDataList.element_mask"
    ]
    knowledge_prefix = encodings["KnowledgeSaveData._list.list_prefix"]
    knowledge_mask = encodings["KnowledgeSaveData._list.element_mask"]
    if "MISSING" in (mount_prefix, mount_mask, knowledge_prefix, knowledge_mask):
        raise UnknownSaveSchemaError("Fixture is missing a required Blackstar encoding")
    return CompatibilityProfile(
        profile_id=profile_id,
        identity=identity,
        mount_list_prefix=int(mount_prefix),
        mount_element_mask_hex=mount_mask,
        knowledge_list_prefix=int(knowledge_prefix),
        knowledge_element_mask_hex=knowledge_mask,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Enroll a copied save schema profile")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = _profile_from_fixture(args.fixture, args.profile_id)
    document = {"profiles": [asdict(profile)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote compatibility profile {profile.profile_id} to {args.output}")


if __name__ == "__main__":
    main()
