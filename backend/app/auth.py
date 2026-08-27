import hashlib
import hmac
import json
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings
from .metrics import current_metrics_context
from .tracing import record_trace_event

_ALLOWED_SCOPES = frozenset({"agent", "file", "session", "metrics", "admin", "*"})


@dataclass(slots=True, frozen=True)
class AuthPrincipal:
    name: str
    scopes: frozenset[str]

    def allows(self, required_scope: str) -> bool:
        return "*" in self.scopes or required_scope in self.scopes


@dataclass(slots=True, frozen=True)
class _Credential:
    principal: AuthPrincipal
    token_digest: bytes


class AuthenticationManager:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.auth_mode == "api_key"
        self.public_paths = frozenset(settings.auth_public_path_list)
        self._credentials: tuple[_Credential, ...] = ()
        if not self.enabled:
            return

        raw = settings.auth_api_keys_json.get_secret_value().strip()
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("AUTH_API_KEYS_JSON 必须是合法 JSON") from exc
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("AUTH_MODE=api_key 时必须配置至少一个 API key")

        credentials: list[_Credential] = []
        for principal_name, spec in parsed.items():
            name = str(principal_name).strip()
            if not name or not isinstance(spec, dict):
                raise ValueError("AUTH_API_KEYS_JSON principal 配置非法")
            token = str(spec.get("token") or "").strip()
            if len(token) < 24 or token.lower() in {"replace-me", "change-me"}:
                raise ValueError(f"AUTH_API_KEYS_JSON 中 {name} 的 token 必须至少 24 字符且不能使用占位值")
            raw_scopes = spec.get("scopes")
            if not isinstance(raw_scopes, list) or not raw_scopes:
                raise ValueError(f"AUTH_API_KEYS_JSON 中 {name} 必须配置 scopes")
            scopes = frozenset(str(scope).strip() for scope in raw_scopes if str(scope).strip())
            invalid = scopes - _ALLOWED_SCOPES
            if invalid:
                raise ValueError(f"AUTH_API_KEYS_JSON 中 {name} 存在未知 scope: {sorted(invalid)}")
            credentials.append(
                _Credential(
                    principal=AuthPrincipal(name=name, scopes=scopes),
                    token_digest=_token_digest(token),
                )
            )
        self._credentials = tuple(credentials)

    def authenticate(self, token: str) -> AuthPrincipal | None:
        candidate = _token_digest(token)
        match: AuthPrincipal | None = None
        for credential in self._credentials:
            if hmac.compare_digest(candidate, credential.token_digest):
                match = credential.principal
        return match


class AuthenticationMiddleware:
    def __init__(self, app: ASGIApp, *, manager: AuthenticationManager) -> None:
        self.app = app
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._manager.enabled:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        if method == "OPTIONS" or path in self._manager.public_paths:
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        token = _bearer_token(headers.get("authorization", ""))
        if token is None:
            _record_auth_failure("missing")
            record_trace_event("auth.rejected", {"deepdesk.auth.reason": "missing"})
            await _auth_error(401, "缺少 Bearer 认证凭据", scope, receive, send)
            return

        principal = self._manager.authenticate(token)
        if principal is None:
            _record_auth_failure("invalid")
            record_trace_event("auth.rejected", {"deepdesk.auth.reason": "invalid"})
            await _auth_error(401, "认证凭据无效", scope, receive, send)
            return

        required_scope = _required_scope(path)
        if not principal.allows(required_scope):
            _record_auth_failure("forbidden")
            record_trace_event(
                "auth.forbidden",
                {"deepdesk.auth.required_scope": required_scope},
            )
            await _auth_error(403, "当前凭据无权访问该资源", scope, receive, send, authenticate=False)
            return

        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["auth_principal"] = principal.name
            state["auth_scopes"] = tuple(sorted(principal.scopes))
        await self.app(scope, receive, send)


def _headers(scope: Scope) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        result[raw_name.decode("latin-1").lower()] = raw_value.decode("latin-1")
    return result


def _bearer_token(value: str) -> str | None:
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _required_scope(path: str) -> str:
    if path.startswith("/agent/"):
        return "agent"
    if path.startswith("/file/"):
        return "file"
    if path.startswith("/session/"):
        return "session"
    if path == "/metrics":
        return "metrics"
    return "admin"


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


async def _auth_error(
    status_code: int,
    message: str,
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    authenticate: bool = True,
) -> None:
    headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
    response = JSONResponse(
        status_code=status_code,
        content={"code": status_code, "message": message, "data": None},
        headers=headers,
    )
    await response(scope, receive, send)


def _record_auth_failure(reason: str) -> None:
    context = current_metrics_context()
    if context is None:
        return
    context.registry.increment(
        "deepdesk_auth_failures_total",
        labels={"reason": reason},
    )
