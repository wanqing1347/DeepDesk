from dataclasses import dataclass
from enum import StrEnum


class PptStatus(StrEnum):
    INIT = "INIT"
    REQUIREMENT = "REQUIREMENT"
    SEARCH = "SEARCH"
    OUTLINE = "OUTLINE"
    TEMPLATE = "TEMPLATE"
    SCHEMA = "SCHEMA"
    RENDER = "RENDER"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PptIntent(StrEnum):
    CREATE_PPT = "CREATE_PPT"
    MODIFY_PPT = "MODIFY_PPT"
    RESUME_PPT = "RESUME_PPT"


@dataclass(slots=True, frozen=True)
class PptIntentResult:
    intent: PptIntent
    reason: str
