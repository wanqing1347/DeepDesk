import json
from typing import Any

from ..persistence.ppt_repository import PptRepository
from ..providers.llm import OpenAICompatibleClient
from .domain import PptIntent, PptIntentResult, PptStatus


class PptIntentRecognizer:
    _RESUME_KEYWORDS = ("继续", "重试", "resume", "retry", "继续执行", "继续生成")
    _NEW_KEYWORDS = ("新建", "重新", "重新生成", "new", "create new")

    def __init__(self, repository: PptRepository, llm: OpenAICompatibleClient) -> None:
        self._repository = repository
        self._llm = llm

    async def recognize(self, conversation_id: str, query: str) -> PptIntentResult:
        latest = self._repository.get_latest_inst(conversation_id)
        if latest is None:
            return PptIntentResult(PptIntent.CREATE_PPT, "会话中无PPT实例，默认新建")

        status = self._status(latest.status)
        error_msg = str(latest.error_msg or "")
        if self._needs_resume(status, error_msg, query):
            return PptIntentResult(PptIntent.RESUME_PPT, f"检测到上次执行未完成，从状态 {status.value} 继续执行")

        if status is PptStatus.SUCCESS:
            return await self._recognize_success_query(query)

        return PptIntentResult(PptIntent.CREATE_PPT, f"状态为 {status.value}，默认新建")

    def _needs_resume(self, status: PptStatus, error_msg: str, query: str) -> bool:
        if error_msg.strip():
            return True
        lower_query = query.lower()
        if any(keyword in lower_query for keyword in self._RESUME_KEYWORDS):
            return True
        if status not in {PptStatus.SUCCESS, PptStatus.INIT}:
            return not any(keyword in lower_query for keyword in self._NEW_KEYWORDS)
        return False

    async def _recognize_success_query(self, query: str) -> PptIntentResult:
        try:
            response = await self._llm.complete(
                [
                    {"role": "system", "content": INTENT_PROMPT},
                    {"role": "user", "content": f"<question>{query}</question>"},
                ],
                [],
            )
            raw = self._assistant_text(response)
            payload = self._parse_json_object(raw)
            intent_raw = str(payload.get("intent") or "").strip()
            reason = str(payload.get("reason") or "").strip()
            intent = PptIntent(intent_raw)
            if intent not in {PptIntent.CREATE_PPT, PptIntent.MODIFY_PPT}:
                raise ValueError(f"SUCCESS状态不支持意图: {intent.value}")
            return PptIntentResult(intent, reason or "LLM意图识别")
        except Exception:
            return PptIntentResult(PptIntent.CREATE_PPT, "意图识别失败，默认新建")

    @staticmethod
    def _status(raw: str | None) -> PptStatus:
        try:
            return PptStatus(str(raw or PptStatus.INIT.value))
        except ValueError:
            return PptStatus.INIT

    @staticmethod
    def _assistant_text(response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message")
        if not isinstance(message, dict):
            return ""
        return str(message.get("content") or "")

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        candidate = raw.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                raise
            value = json.loads(candidate[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("意图识别结果不是 JSON object")
        return value


INTENT_PROMPT = """你是PPT意图识别器。当前会话已经存在一个成功生成的PPT。
判断用户是要创建一个全新的PPT，还是修改当前已有PPT。
只输出严格JSON对象：
{"intent":"CREATE_PPT|MODIFY_PPT","reason":"简短原因"}
不要输出 RESUME_PPT；成功状态下继续/修改已有内容属于 MODIFY_PPT，明确另起主题/新建属于 CREATE_PPT。"""
