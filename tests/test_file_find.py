"""Recursive and fuzzy local file discovery."""

from __future__ import annotations

from whitenight.tools.base import ToolContext
from whitenight.tools.files import FileFindTool


def _find(tmp_path, **params):
    tool = FileFindTool()
    validated = tool.validate({"root": str(tmp_path), **params})
    return tool.execute(ToolContext(data_dir=str(tmp_path)), validated)


def test_file_find_recurses_by_default_and_can_limit_to_root(tmp_path) -> None:
    nested = tmp_path / "nested" / "deep"
    nested.mkdir(parents=True)
    target = nested / "report.txt"
    target.write_text("report", encoding="utf-8")

    recursive = _find(tmp_path, names=["report.txt"], match_mode="exact")
    shallow = _find(
        tmp_path,
        names=["report.txt"],
        match_mode="exact",
        recursive=False,
    )

    assert [source.uri for source in recursive.sources] == [str(target)]
    assert shallow.sources == []


def test_auto_match_prefers_exact_name_over_fuzzy_candidates(tmp_path) -> None:
    exact = tmp_path / "report.txt"
    exact.write_text("exact", encoding="utf-8")
    (tmp_path / "report-final.txt").write_text("fuzzy", encoding="utf-8")

    result = _find(tmp_path, names=["report.txt"], match_mode="auto")

    assert [source.uri for source in result.sources] == [str(exact)]
    assert result.metadata["used_fuzzy"] is False
    assert result.metadata["needs_confirmation"] is False


def test_fuzzy_match_ranks_candidates_and_marks_count_mismatch(tmp_path) -> None:
    closest = tmp_path / "annual-report.pdf"
    closest.write_text("closest", encoding="utf-8")
    alternative = tmp_path / "annual-reports.pdf"
    alternative.write_text("alternative", encoding="utf-8")
    (tmp_path / "unrelated.txt").write_text("no", encoding="utf-8")

    result = _find(
        tmp_path,
        names=["annual-reprot.pdf"],
        match_mode="fuzzy",
        expected_count=1,
        similarity_threshold=0.6,
    )

    assert result.sources[0].uri == str(closest)
    assert {source.uri for source in result.sources} == {str(closest), str(alternative)}
    assert result.metadata["used_fuzzy"] is True
    assert result.metadata["count"] == 2
    assert result.metadata["expected_count"] == 1
    assert result.metadata["needs_confirmation"] is True


def test_fuzzy_single_match_does_not_require_confirmation(tmp_path) -> None:
    target = tmp_path / "general.jsonl"
    target.write_text("{}", encoding="utf-8")

    result = _find(
        tmp_path,
        names=["genral.jsonl"],
        match_mode="auto",
        expected_count=1,
        similarity_threshold=0.7,
    )

    assert [source.uri for source in result.sources] == [str(target)]
    assert result.metadata["used_fuzzy"] is True
    assert result.metadata["needs_confirmation"] is False


def test_result_limit_cannot_hide_an_uncovered_query(tmp_path) -> None:
    (tmp_path / "report-final.txt").write_text("one", encoding="utf-8")
    (tmp_path / "report-draft.txt").write_text("two", encoding="utf-8")
    (tmp_path / "budget-final.txt").write_text("three", encoding="utf-8")

    result = _find(
        tmp_path,
        names=["report.txt", "budget.txt"],
        match_mode="fuzzy",
        expected_count=2,
        similarity_threshold=0.5,
        max_results=2,
    )

    assert result.metadata["truncated"] is True
    assert result.metadata["needs_confirmation"] is True


def test_fuzzy_match_rejects_short_stem_and_wrong_extension_false_positives(
    tmp_path,
) -> None:
    for name in ("d.py", "methods.js", "ET.js", "ME.js", "TH.js"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    result = _find(
        tmp_path,
        names=["Methods_4改.docx"],
        match_mode="auto",
        similarity_threshold=0.68,
    )

    assert result.sources == []
    assert result.metadata["unmatched_names"] == ["Methods_4改.docx"]
