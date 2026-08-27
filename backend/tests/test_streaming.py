from app.streaming import ThinkTagStreamParser


def test_think_tag_parser_handles_tags_split_across_chunks() -> None:
    parser = ThinkTagStreamParser()

    segments = []
    segments.extend(parser.feed("普通<thi"))
    segments.extend(parser.feed("nk>思考过程</th"))
    segments.extend(parser.feed("ink>最终"))
    segments.extend(parser.finish())

    assert [(segment.content, segment.thinking) for segment in segments] == [
        ("普通", False),
        ("思考过程", True),
        ("最终", False),
    ]


def test_think_tag_parser_flushes_unclosed_thinking_content() -> None:
    parser = ThinkTagStreamParser()

    segments = parser.feed("<think>尚未结束") + parser.finish()

    assert [(segment.content, segment.thinking) for segment in segments] == [("尚未结束", True)]
