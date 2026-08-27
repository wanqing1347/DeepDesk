import asyncio
import json
import os
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

import httpx

from ..config import Settings
from ..files.storage import ObjectStore
from ..persistence.models import AiPptInst, AiPptTemplate
from ..providers.retry import is_retryable_http_error, sleep_before_retry
from ..tracing import inject_trace_headers, trace_provider_call

PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class PptRenderer(Protocol):
    async def render(self, inst: AiPptInst, template: AiPptTemplate, ppt_schema: str) -> str: ...


class PptImageGenerator(Protocol):
    async def generate(self, prompt: str) -> str | None: ...


class PythonPptRenderer:
    """Adapter around the local PPT rendering engine."""

    def __init__(self, settings: Settings, object_store: ObjectStore | None) -> None:
        self._settings = settings
        self._object_store = object_store

    async def render(self, inst: AiPptInst, template: AiPptTemplate, ppt_schema: str) -> str:
        if self._object_store is None:
            raise RuntimeError("PPT渲染需要配置 MinIO 对象存储")
        script = Path(self._settings.ppt_render_script_path).expanduser().resolve()
        template_path = Path(template.file_path).expanduser().resolve()
        if not script.is_file():
            raise RuntimeError(f"PPT渲染脚本不存在: {script}")
        if not template_path.is_file():
            raise RuntimeError(f"PPT模板文件不存在: {template_path}")

        output_dir = Path(self._settings.ppt_output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = f"ppt_{inst.id}_{uuid.uuid4().hex[:12]}.pptx"
        output_path = output_dir / output_name
        schema_temp_path: Path | None = None
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        if len(ppt_schema) > self._settings.ppt_schema_env_threshold_chars:
            handle, raw_path = tempfile.mkstemp(prefix="ppt_schema_", suffix=".json")
            os.close(handle)
            schema_temp_path = Path(raw_path)
            schema_temp_path.write_text(ppt_schema, encoding="utf-8")
            env["PPT_SCHEMA_FILE"] = str(schema_temp_path)
            env.pop("PPT_SCHEMA", None)
        else:
            env["PPT_SCHEMA"] = ppt_schema
            env.pop("PPT_SCHEMA_FILE", None)

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            "--template",
            str(template_path),
            "--output",
            str(output_path),
            cwd=str(script.parent),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.ppt_render_timeout_seconds,
            )
        except TimeoutError as exc:
            await self._terminate(process)
            raise RuntimeError("PPT Python渲染超时") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        finally:
            if schema_temp_path is not None:
                schema_temp_path.unlink(missing_ok=True)

        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        if process.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError(f"PPT Python渲染失败: {output[-4000:]}")
        if not output_path.is_file():
            raise RuntimeError(f"PPT未生成: {output_path}")

        try:
            file_bytes = await asyncio.to_thread(output_path.read_bytes)
            object_name = f"ppt/{inst.conversation_id}/{output_name}"
            return await asyncio.to_thread(
                self._object_store.upload,
                object_name=object_name,
                content=file_bytes,
                content_type=PPTX_CONTENT_TYPE,
            )
        finally:
            output_path.unlink(missing_ok=True)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            process.kill()
            await process.wait()


class QwenPptImageGenerator:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("transport and client cannot both be provided")
        self._settings = settings
        self._transport = transport
        self._client = client

    @asynccontextmanager
    async def _client_scope(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(
            timeout=self._settings.ppt_image_timeout_seconds,
            transport=self._transport,
        ) as client:
            yield client

    async def generate(self, prompt: str) -> str | None:
        if not self._settings.openai_api_key.strip() or self._settings.openai_api_key == "replace-me":
            return None
        payload = {
            "model": self._settings.ppt_image_model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {
                "negative_prompt": (
                    "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，"
                    "过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。"
                ),
                "prompt_extend": True,
                "watermark": False,
                "size": "1664*928",
            },
        }
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        with trace_provider_call("ppt_image", "generate"):
            traced_headers = inject_trace_headers(headers)
            async with self._client_scope() as client:
                for attempt in range(self._settings.provider_max_retries + 1):
                    try:
                        response = await client.post(
                            self._settings.ppt_image_endpoint,
                            headers=traced_headers,
                            json=payload,
                            timeout=self._settings.ppt_image_timeout_seconds,
                        )
                        response.raise_for_status()
                        data = response.json()
                        break
                    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                        if attempt >= self._settings.provider_max_retries or not is_retryable_http_error(exc):
                            raise
                        await sleep_before_retry(
                            retry_number=attempt + 1,
                            base_seconds=self._settings.provider_retry_base_seconds,
                            max_seconds=self._settings.provider_retry_max_seconds,
                            provider="ppt_image",
                            operation="generate",
                        )
                else:
                    raise RuntimeError("PPT image request retry loop exited unexpectedly")
        try:
            return str(data["output"]["choices"][0]["message"]["content"][0]["image"])
        except (KeyError, IndexError, TypeError):
            return None


async def materialize_ppt_images(
    schema: dict[str, object],
    *,
    conversation_id: str,
    generator: PptImageGenerator,
    object_store: ObjectStore | None,
    download_timeout_seconds: int,
    http_client: httpx.AsyncClient | None = None,
    max_retries: int = 0,
    retry_base_seconds: float = 0.5,
    retry_max_seconds: float = 5.0,
) -> list[tuple[str, bool]]:
    """Generate missing image/background fields when possible."""

    tasks: list[tuple[str, dict[str, object], str]] = []
    slides = schema.get("slides")
    if not isinstance(slides, list):
        return []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        data = slide.get("data")
        if not isinstance(data, dict):
            continue
        for key, raw_field in data.items():
            if not isinstance(raw_field, dict):
                continue
            field_type = str(raw_field.get("type") or "").lower()
            if field_type not in {"image", "background"}:
                continue
            if str(raw_field.get("url") or "").strip():
                continue
            prompt = str(raw_field.get("content") or "").strip()
            if prompt:
                tasks.append((str(key), raw_field, prompt))

    if not tasks:
        return []

    outcomes: list[tuple[str, bool]] = []
    async with _async_client_scope(http_client, timeout_seconds=download_timeout_seconds) as client:
        for index, (key, field, prompt) in enumerate(tasks, start=1):
            try:
                generated_url = await generator.generate(prompt)
                if not generated_url or object_store is None:
                    raise RuntimeError("图片生成或对象存储未配置")
                image_bytes = await _download_image_bytes(
                    client,
                    generated_url,
                    timeout_seconds=download_timeout_seconds,
                    max_retries=max_retries,
                    retry_base_seconds=retry_base_seconds,
                    retry_max_seconds=retry_max_seconds,
                )
                object_name = f"ppt/{conversation_id}/images/{uuid.uuid4().hex}_{index}.png"
                minio_url = await asyncio.to_thread(
                    object_store.upload,
                    object_name=object_name,
                    content=image_bytes,
                    content_type="image/png",
                )
                field["url"] = minio_url
                outcomes.append((key, True))
            except asyncio.CancelledError:
                raise
            except Exception:
                field["url"] = ""
                outcomes.append((key, False))
    return outcomes


@asynccontextmanager
async def _async_client_scope(
    client: httpx.AsyncClient | None,
    *,
    timeout_seconds: int,
):
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=timeout_seconds) as owned_client:
        yield owned_client


async def _download_image_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: int,
    max_retries: int,
    retry_base_seconds: float,
    retry_max_seconds: float,
) -> bytes:
    with trace_provider_call("ppt_image", "download"):
        for attempt in range(max_retries + 1):
            try:
                response = await client.get(url, timeout=timeout_seconds)
                response.raise_for_status()
                return response.content
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt >= max_retries or not is_retryable_http_error(exc):
                    raise
                await sleep_before_retry(
                    retry_number=attempt + 1,
                    base_seconds=retry_base_seconds,
                    max_seconds=retry_max_seconds,
                    provider="ppt_image",
                    operation="download",
                )
    raise RuntimeError("PPT image download retry loop exited unexpectedly")


def serialize_schema(schema: dict[str, object]) -> str:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
