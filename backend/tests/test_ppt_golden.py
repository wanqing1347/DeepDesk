"""Stable PPT state-machine contract regression tests."""

import json

from app.persistence.models import AiPptInst
from app.ppt.domain import PptIntent, PptStatus


def _state_snapshot(inst: AiPptInst) -> dict[str, object]:
    payload = json.loads(inst.ppt_schema or "{}") if inst.ppt_schema else {}
    slides = payload.get("slides") if isinstance(payload, dict) else None
    return {
        "status": str(inst.status or ""),
        "hasRequirement": bool(str(inst.requirement or "").strip()),
        "hasSearchInfo": bool(str(inst.search_info or "").strip()),
        "hasTemplateCode": bool(str(inst.template_code or "").strip()),
        "hasOutline": bool(str(inst.outline or "").strip()),
        "hasPptSchema": bool(str(inst.ppt_schema or "").strip()),
        "schemaSlideCount": len(slides) if isinstance(slides, list) else 0,
        "hasFileUrl": bool(str(inst.file_url or "").strip()),
        "hasError": bool(str(inst.error_msg or "").strip()),
    }


def test_ppt_contract_exposes_expected_terminal_states() -> None:
    assert PptStatus.SUCCESS.value == "SUCCESS"
    assert PptStatus.FAILED.value == "FAILED"
    assert PptIntent.CREATE_PPT.value == "CREATE_PPT"
    assert PptIntent.MODIFY_PPT.value == "MODIFY_PPT"
    assert PptIntent.RESUME_PPT.value == "RESUME_PPT"


def test_ppt_state_snapshot_tracks_presence_and_page_count() -> None:
    inst = AiPptInst(
        conversation_id="regression",
        status="SUCCESS",
        requirement="req",
        search_info="search",
        template_code="ai",
        outline="outline",
        ppt_schema=json.dumps({"slides": [{}, {}]}),
        file_url="https://example.test/generated.pptx",
        error_msg="",
    )

    assert _state_snapshot(inst) == {
        "status": "SUCCESS",
        "hasRequirement": True,
        "hasSearchInfo": True,
        "hasTemplateCode": True,
        "hasOutline": True,
        "hasPptSchema": True,
        "schemaSlideCount": 2,
        "hasFileUrl": True,
        "hasError": False,
    }
