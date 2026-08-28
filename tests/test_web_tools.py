"""搜索/页面工具测试：来源保留与不可信内容标记。"""

from __future__ import annotations

from whitenight.tools.base import ToolContext
from whitenight.tools.web import (
    FetchedPage,
    SearchResult,
    VolcGlobalSearchProvider,
    WebFetchTool,
    WebSearchTool,
    _extract_ddg_url,
)


def test_volc_global_search_maps_documents(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {
                "Result": {
                    "Documents": [
                        {"Title": "火山", "Url": "https://example.com", "Snippet": "摘要"}
                    ]
                }
            }

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return Response()

    monkeypatch.setattr("whitenight.tools.web.httpx.Client", Client)
    results = VolcGlobalSearchProvider(lambda: "secret").search("测试", 3)
    assert results[0].url == "https://example.com"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["trust_env"] is False
    assert captured["json"] == {
        "Query": "测试",
        "DocCount": 3,
        "MaxSnippetLength": 500,
        "MaxImageCountPerDoc": 0,
    }


class FakeSearchProvider:
    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                title="结果一",
                url="https://example.com/a",
                snippet="摘要一",
                retrieved_at="",
            )
        ]

    def fetch(self, url: str, max_chars: int = 12000) -> FetchedPage:
        del max_chars
        return FetchedPage(
            url=url,
            final_url=url + "/final",
            title="示例页",
            text="网页正文内容",
            truncated=False,
            untrusted=True,
        )


def test_search_keeps_sources() -> None:
    result = WebSearchTool(FakeSearchProvider()).execute(
        ToolContext(data_dir="data"), WebSearchTool().validate({"query": "测试"})
    )
    assert result.ok
    assert result.sources[0].uri == "https://example.com/a"
    assert result.metadata["untrusted"] is True


def test_fetch_marks_untrusted_and_keeps_final_url() -> None:
    tool = WebFetchTool(FakeSearchProvider())
    result = tool.execute(
        ToolContext(data_dir="data"), tool.validate({"url": "https://example.com/x"})
    )
    assert result.ok
    assert "网页正文内容" in result.content
    assert result.sources[0].uri == "https://example.com/x/final"
    assert result.metadata["untrusted"] is True


def test_ddg_redirect_url_extraction() -> None:
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fp&rut=x"
    assert _extract_ddg_url(href) == "https://example.com/p"
    assert _extract_ddg_url("https://example.com/direct") == "https://example.com/direct"
    assert _extract_ddg_url("javascript:alert(1)") == ""
