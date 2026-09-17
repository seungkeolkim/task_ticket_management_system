import hashlib
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, retry_after: int = 0):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(message)


@dataclass(frozen=True)
class Identity:
    id: int
    login_id: str
    display_name: str
    organization: str
    system_role: str
    must_change_password: bool
    session_id: int

    @property
    def initials(self) -> str:
        return self.display_name[:2]

    @property
    def is_admin(self) -> bool:
        return self.system_role == "SYSTEM_ADMIN"


def normalize_login_id(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", normalized):
        raise AuthError(
            "invalid_login_id", "로그인 ID는 영문·숫자·점·밑줄·하이픈 3~100자로 입력하세요."
        )
    return normalized


def validate_password(value: str) -> None:
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise AuthError("invalid_password", "비밀번호는 12~128자로 입력하세요.")
    if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AuthError(
            "invalid_password", "공백만 있거나 제어문자가 포함된 비밀번호는 사용할 수 없습니다."
        )


def hash_password(value: str) -> str:
    validate_password(value)
    return _hasher.hash(value)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(32))


def verify_password(value: str, stored_hash: str | None) -> bool:
    # Bound work before Argon2. No password normalization or truncation.
    if len(value) > PASSWORD_MAX_LENGTH:
        return False
    try:
        return _hasher.verify(stored_hash or _dummy_hash(), value) and stored_hash is not None
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        if stored_hash is not None:
            verify_password(value, None)
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
