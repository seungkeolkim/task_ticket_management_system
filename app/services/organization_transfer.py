"""조직 계층 JSON 내보내기와 비파괴 가져오기를 처리한다."""

import hashlib
import hmac
import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.transaction import request_transaction
from app.domain.auth import AuthError, Identity
from app.models import Organization
from app.repositories import administration as repository
from app.repositories.auth import lock_security_write
from app.services.administration import require_administrator
from app.services.auth import record_audit_event

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 16 * 1_048_576
MAX_ORGANIZATIONS = 2_000
MAX_DEPTH = 32


@dataclass(frozen=True)
class OrganizationRecord:
    """JSON과 DB 상태를 비교하는 조직의 안정 식별자 기반 값이다."""

    key: str
    name: str
    description: str
    is_active: bool
    parent_key: str | None


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSON 객체의 중복 field를 조용히 덮어쓰지 않는다."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 객체에 중복된 항목이 있습니다.")
        result[key] = value
    return result


def parse_organization_document(document_bytes: bytes) -> list[OrganizationRecord]:
    """크기·schema·계층·중복 key와 형제 이름을 검증한다."""
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        raise AuthError(
            "organization_import_too_large", "조직 JSON 파일은 16MB 이하여야 합니다.", 413
        )
    try:
        document = json.loads(
            document_bytes.decode("utf-8-sig"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise AuthError(
            "invalid_organization_json", "UTF-8 JSON 파일을 확인하세요.", 422
        ) from error
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "organizations"}
        or type(document["schema_version"]) is not int
        or document["schema_version"] != SCHEMA_VERSION
        or not isinstance(document["organizations"], list)
    ):
        raise AuthError(
            "invalid_organization_schema", "조직 JSON schema version과 형식을 확인하세요.", 422
        )

    records = []
    seen_keys = set()
    sibling_names: dict[str | None, set[str]] = defaultdict(set)
    pending = [(node, None, 1) for node in reversed(document["organizations"])]
    while pending:
        node, parent_key, depth = pending.pop()
        if depth > MAX_DEPTH or len(records) >= MAX_ORGANIZATIONS:
            raise AuthError(
                "organization_import_limit", "조직 수 또는 계층 깊이 제한을 초과했습니다.", 422
            )
        if not isinstance(node, dict) or set(node) != {
            "key",
            "name",
            "description",
            "is_active",
            "children",
        }:
            raise AuthError("invalid_organization_schema", "조직 항목의 필드를 확인하세요.", 422)
        key = node["key"]
        name = node["name"]
        description = node["description"]
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 64
            or key != key.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in key)
            or not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 200
            or not isinstance(description, str)
            or len(description.strip()) > 4000
            or type(node["is_active"]) is not bool
            or not isinstance(node["children"], list)
        ):
            raise AuthError(
                "invalid_organization_schema", "조직 항목의 값과 길이를 확인하세요.", 422
            )
        normalized_name = name.strip()
        if key in seen_keys:
            raise AuthError("duplicate_organization_key", "조직 JSON에 중복된 key가 있습니다.", 422)
        if normalized_name in sibling_names[parent_key]:
            raise AuthError(
                "duplicate_organization_name",
                "조직 JSON의 같은 상위 조직에 이름이 중복됩니다.",
                422,
            )
        seen_keys.add(key)
        sibling_names[parent_key].add(normalized_name)
        records.append(
            OrganizationRecord(
                key, normalized_name, description.strip(), node["is_active"], parent_key
            )
        )
        for child in reversed(node["children"]):
            pending.append((child, key, depth + 1))
    return records


def export_organization_document(session: Session, actor: Identity) -> bytes:
    """전체 조직 트리를 versioned UTF-8 JSON으로 직렬화한다."""
    require_administrator(session, actor)
    rows = repository.list_organizations(session)
    _, errors = _plan_import([], _existing_records(rows))
    if errors:
        raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
    nodes_by_id = {
        row.id: {
            "key": row.key,
            "name": row.name,
            "description": row.description,
            "is_active": row.is_active,
            "children": [],
        }
        for row in rows
    }
    roots = []
    for row in rows:
        node = nodes_by_id[row.id]
        if row.parent_id is None:
            roots.append(node)
        elif row.parent_id in nodes_by_id:
            nodes_by_id[row.parent_id]["children"].append(node)
        else:
            raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
    if len(nodes_by_id) != len(rows):
        raise AuthError("invalid_organization_tree", "조직 구조를 확인하세요.", 409)
    return (
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "organizations": roots},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _existing_records(rows: list[Organization]) -> dict[str, OrganizationRecord]:
    """현재 DB 조직을 key 기반의 비교 값으로 변환한다."""
    keys_by_id = {row.id: row.key for row in rows}
    return {
        row.key: OrganizationRecord(
            row.key,
            row.name,
            row.description,
            row.is_active,
            keys_by_id.get(row.parent_id),
        )
        for row in rows
    }


def _state_digest(records: dict[str, OrganizationRecord]) -> bytes:
    """미리보기의 조직 상태 fingerprint를 계산한다."""
    values = [asdict(records[key]) for key in sorted(records)]
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).digest()


def _document_digest(records: list[OrganizationRecord]) -> bytes:
    """정규화된 import 문서의 fingerprint를 계산한다."""
    values = [asdict(record) for record in records]
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).digest()


def _preview_token(
    session_token: str,
    actor_id: int,
    imported: list[OrganizationRecord],
    existing: dict[str, OrganizationRecord],
) -> str:
    """미리보기 내용을 현재 session·DB 상태에 결합한다."""
    message = (
        b"organization-import-preview-v1:"
        + str(actor_id).encode("ascii")
        + _document_digest(imported)
        + _state_digest(existing)
    )
    return hmac.new(session_token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _plan_import(
    imported: list[OrganizationRecord],
    existing: dict[str, OrganizationRecord],
) -> tuple[list[dict[str, object]], list[str]]:
    """누락 조직을 보존한 최종 트리의 변경·충돌을 계산한다."""
    final_records = existing | {record.key: record for record in imported}
    errors = []
    occupied_names: dict[tuple[str | None, str], str] = {}
    for record in final_records.values():
        location = (record.parent_key, record.name)
        other_key = occupied_names.get(location)
        if other_key is not None and other_key != record.key:
            errors.append(f"같은 상위 조직에 이름이 중복됩니다: {record.name}")
        occupied_names[location] = record.key

    for record in final_records.values():
        visited = set()
        ancestor_key: str | None = record.key
        while ancestor_key is not None:
            if ancestor_key in visited:
                errors.append(f"조직 계층에 순환이 있습니다: {record.key}")
                break
            visited.add(ancestor_key)
            ancestor = final_records.get(ancestor_key)
            if ancestor is None:
                errors.append(f"상위 조직을 찾을 수 없습니다: {record.key}")
                break
            ancestor_key = ancestor.parent_key

    changes = []
    for record in imported:
        previous = existing.get(record.key)
        changed_fields = [
            field_name
            for field_name in ("name", "parent_key", "description", "is_active")
            if previous is not None and getattr(previous, field_name) != getattr(record, field_name)
        ]
        action = "ADD" if previous is None else "UPDATE" if changed_fields else "UNCHANGED"
        changes.append(
            {
                "action": action,
                "key": record.key,
                "name": record.name,
                "parent_key": record.parent_key,
                "changed_fields": changed_fields,
            }
        )
        needs_active_parent = (
            previous is None
            or previous.parent_key != record.parent_key
            or (not previous.is_active and record.is_active)
        )
        if not needs_active_parent:
            continue
        ancestor_key = record.parent_key
        visited = set()
        while ancestor_key is not None and ancestor_key not in visited:
            visited.add(ancestor_key)
            ancestor = final_records.get(ancestor_key)
            if ancestor is None:
                break
            if not ancestor.is_active and (previous is not None or ancestor_key in existing):
                errors.append(f"상위 조직이 비활성 상태입니다: {record.key}")
                break
            ancestor_key = ancestor.parent_key
    return changes, list(dict.fromkeys(errors))[:20]


def preview_organization_import(
    session: Session,
    actor: Identity,
    document_bytes: bytes,
    session_token: str,
) -> dict[str, object]:
    """조직 JSON의 추가·갱신·충돌과 적용 token을 반환한다."""
    require_administrator(session, actor)
    imported = parse_organization_document(document_bytes)
    existing = _existing_records(repository.list_organizations(session))
    changes, errors = _plan_import(imported, existing)
    return {
        "changes": changes,
        "errors": errors,
        "preview_token": None
        if errors
        else _preview_token(session_token, actor.id, imported, existing),
        "add_count": sum(change["action"] == "ADD" for change in changes),
        "update_count": sum(change["action"] == "UPDATE" for change in changes),
        "unchanged_count": sum(change["action"] == "UNCHANGED" for change in changes),
    }


def apply_organization_import(
    session: Session,
    actor: Identity,
    document_bytes: bytes,
    session_token: str,
    preview_token: str,
    ip_address: str,
) -> dict[str, int]:
    """미리보기와 동일한 상태에서만 조직 추가·갱신을 원자적으로 적용한다."""
    imported = parse_organization_document(document_bytes)
    logger.debug("organization_import_started actor_id=%s", actor.id)
    try:
        with request_transaction(session):
            lock_security_write(session)
            require_administrator(session, actor)
            rows = repository.list_organizations(session)
            existing = _existing_records(rows)
            changes, errors = _plan_import(imported, existing)
            expected_token = _preview_token(session_token, actor.id, imported, existing)
            if errors or not hmac.compare_digest(preview_token, expected_token):
                raise AuthError(
                    "organization_import_stale",
                    "조직 구조가 변경되었습니다. 다시 미리보기를 확인하세요.",
                    409,
                )

            rows_by_key = {row.key: row for row in rows}
            for change in changes:
                if change["action"] == "UPDATE":
                    row = rows_by_key[change["key"]]
                    row.name = f"__organization_import_{uuid4().hex}"
                    row.parent_id = None
            session.flush()
            for record in imported:
                if record.key not in rows_by_key:
                    row = Organization(
                        key=record.key,
                        name=f"__organization_import_{uuid4().hex}",
                        parent_id=None,
                        description=record.description,
                        is_active=True,
                    )
                    session.add(row)
                    rows_by_key[record.key] = row
            session.flush()
            for record, change in zip(imported, changes, strict=True):
                if change["action"] == "UNCHANGED":
                    continue
                row = rows_by_key[record.key]
                row.name = record.name
                row.parent_id = rows_by_key[record.parent_key].id if record.parent_key else None
                row.description = record.description
                row.is_active = record.is_active
            session.flush()
            for change in changes:
                if change["action"] == "UNCHANGED":
                    continue
                row = rows_by_key[change["key"]]
                record_audit_event(
                    session,
                    "organization.imported",
                    actor.id,
                    target_type="organization",
                    target_id=str(row.id),
                    ip_address=ip_address,
                    details={
                        "operation": change["action"],
                        "changed_fields": change["changed_fields"],
                    },
                )
            result = {
                "added": sum(change["action"] == "ADD" for change in changes),
                "updated": sum(change["action"] == "UPDATE" for change in changes),
                "unchanged": sum(change["action"] == "UNCHANGED" for change in changes),
            }
    except AuthError as error:
        logger.info("organization_import_rejected actor_id=%s code=%s", actor.id, error.code)
        raise
    except IntegrityError:
        logger.info("organization_import_rejected actor_id=%s code=conflict", actor.id)
        raise AuthError(
            "organization_import_conflict",
            "조직 구조가 충돌합니다. 다시 미리보기를 확인하세요.",
            409,
        ) from None
    except Exception:
        logger.exception("organization_import_failed actor_id=%s", actor.id)
        raise
    logger.info(
        "organization_import_applied actor_id=%s added=%s updated=%s",
        actor.id,
        result["added"],
        result["updated"],
    )
    return result
