from dataclasses import dataclass


@dataclass(slots=True)
class StreamSegment:
    content: str
    thinking: bool


class ThinkTagStreamParser:
    """Incrementally split <think>...</think> from normal streamed content."""

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False

    def feed(self, chunk: str) -> list[StreamSegment]:
        if not chunk:
            return []
        self._buffer += chunk
        output: list[StreamSegment] = []

        while self._buffer:
            target = self._CLOSE if self._in_think else self._OPEN
            index = self._buffer.find(target)
            if index >= 0:
                if index > 0:
                    output.append(StreamSegment(self._buffer[:index], self._in_think))
                self._buffer = self._buffer[index + len(target) :]
                self._in_think = not self._in_think
                continue

            safe_length = len(self._buffer) - self._partial_tag_suffix_length(self._buffer, target)
            if safe_length <= 0:
                break
            output.append(StreamSegment(self._buffer[:safe_length], self._in_think))
            self._buffer = self._buffer[safe_length:]

        return output

    def finish(self) -> list[StreamSegment]:
        if not self._buffer:
            return []
        segment = StreamSegment(self._buffer, self._in_think)
        self._buffer = ""
        return [segment]

    @staticmethod
    def _partial_tag_suffix_length(value: str, tag: str) -> int:
        max_length = min(len(value), len(tag) - 1)
        for length in range(max_length, 0, -1):
            if value.endswith(tag[:length]):
                return length
        return 0
