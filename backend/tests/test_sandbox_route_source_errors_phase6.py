from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from app.api import sandbox as sandbox_api
from app.schemas.sandbox import SandboxRunRequest
from app.services.source_manager import SourceNotConfiguredError, SourceUnavailableError
from fastapi import HTTPException


@pytest.mark.parametrize(
    ("inspection_error", "expected_status", "expected_code"),
    [
        (SourceNotConfiguredError, 409, "sandbox_not_configured"),
        (SourceUnavailableError, 503, "sandbox_unavailable"),
    ],
)
def test_sandbox_route_maps_sandbox_inspection_errors_safely(
    monkeypatch: pytest.MonkeyPatch,
    inspection_error: type[Exception],
    expected_status: int,
    expected_code: str,
) -> None:
    artifact = SimpleNamespace(source_id="bookstore-demo")

    monkeypatch.setattr(sandbox_api, "load_verified_artifact", lambda *_args: artifact)
    monkeypatch.setattr(
        sandbox_api, "sandbox_lifecycle_lock", lambda *_args, **_kwargs: nullcontext()
    )
    monkeypatch.setattr(sandbox_api, "assert_no_active_checkpoint_session", lambda: None)

    def fail_inspection(_settings: object) -> None:
        raise inspection_error("sanitized test failure")

    monkeypatch.setattr(sandbox_api, "inspect_sandbox", fail_inspection)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=object())))

    with pytest.raises(HTTPException) as raised:
        sandbox_api.run_artifact_in_sandbox(
            "bookstore-demo",
            "sp0123456789ab",
            SandboxRunRequest(confirm=True),
            request,
        )

    assert raised.value.status_code == expected_status
    assert raised.value.detail == {"error": expected_code}
