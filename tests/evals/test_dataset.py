import json
from pathlib import Path

import pytest

from evals.dataset import DatasetError, load_case, load_cases

PROFILE = {
    "target_role": "Backend Developer",
    "seniority": "mid",
    "total_years_coding": 5,
    "stacks": [{"name": "Springboot", "years": 3, "level": "working"}],
    "languages": [{"name": "Inglês", "level": "C1"}],
    "notable_facts": ["Built a payments API"],
}
SPEC = {
    "language": "en",
    "expected_outcome": "borderline",
    "requirements": [{"match": "python", "verdict": "met"}],
}


def make_case(root: Path, case_id: str = "en-99", **changes: object) -> Path:
    folder = root / case_id
    folder.mkdir()
    (folder / "resume.txt").write_text("Jane Doe\nExperience\n")
    (folder / "job.txt").write_text("Requirements:\n- Python\n")
    spec = {**SPEC, **changes}
    (folder / "profile.json").write_text(json.dumps(PROFILE))
    (folder / "case.json").write_text(json.dumps(spec))
    return folder


def test_a_valid_case_loads(tmp_path: Path) -> None:
    case = load_case(make_case(tmp_path))

    assert case.id == "en-99" and case.language == "en"
    assert case.expected_outcome == "borderline"
    assert [(e.match, e.verdict) for e in case.expected] == [("python", "met")]
    assert case.resume_text.startswith("Jane Doe") and "Python" in case.job_text
    assert case.profile.target_role == "Backend Developer"
    assert case.document.multi_column is False and case.document.table_count == 0


def test_the_profile_is_read_as_the_analysis_reads_it(tmp_path: Path) -> None:
    facts = load_case(make_case(tmp_path)).profile_facts()

    assert [s.name for s in facts.stacks] == ["spring boot"]
    assert [lang.name for lang in facts.languages] == ["english"]
    assert facts.total_years_coding == 5 and facts.notable_facts == ["Built a payments API"]


def test_the_document_facts_make_a_parsed_document(tmp_path: Path) -> None:
    case = load_case(
        make_case(tmp_path, document={"multi_column": True, "table_count": 2, "page_count": 3})
    )

    document = case.parsed_document()

    assert document.multi_column and document.table_count == 2 and document.page_count == 3
    assert document.text == case.resume_text and document.file_type == "pdf"


def test_cases_load_in_id_order(tmp_path: Path) -> None:
    for case_id in ("pt-02", "en-01", "pt-01"):
        make_case(tmp_path, case_id)

    assert [case.id for case in load_cases(tmp_path)] == ["en-01", "pt-01", "pt-02"]


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"requirements": [{"match": "python", "verdict": "great"}]}, "verdict"),
        ({"expected_outcome": "maybe"}, "expected_outcome"),
        ({"requirements": [{"match": "", "verdict": "met"}]}, "match"),
        ({"requirements": []}, "requirements"),
        ({"language": "fr"}, "language"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_an_invalid_case_names_the_case_and_the_problem(
    tmp_path: Path, changes: dict[str, object], problem: str
) -> None:
    folder = make_case(tmp_path, "en-42", **changes)

    with pytest.raises(DatasetError) as error:
        load_case(folder)

    assert str(error.value).startswith("case en-42:") and problem in str(error.value)
    assert error.value.case_id == "en-42"


@pytest.mark.parametrize("name", ["resume.txt", "job.txt", "profile.json", "case.json"])
def test_a_missing_file_is_reported(tmp_path: Path, name: str) -> None:
    folder = make_case(tmp_path, "pt-07")
    (folder / name).unlink()

    with pytest.raises(DatasetError, match=f"case pt-07: missing file {name}"):
        load_case(folder)


def test_an_empty_file_is_reported(tmp_path: Path) -> None:
    folder = make_case(tmp_path, "pt-08")
    (folder / "job.txt").write_text("  \n")

    with pytest.raises(DatasetError, match="case pt-08: job.txt is empty"):
        load_case(folder)


@pytest.mark.parametrize("name", ["profile.json", "case.json"])
def test_invalid_json_is_reported(tmp_path: Path, name: str) -> None:
    folder = make_case(tmp_path, "en-77")
    (folder / name).write_text("{not json")

    with pytest.raises(DatasetError, match=f"case en-77: {name} is not valid JSON"):
        load_case(folder)


def test_an_invalid_profile_is_reported(tmp_path: Path) -> None:
    folder = make_case(tmp_path, "en-78")
    (folder / "profile.json").write_text(json.dumps({**PROFILE, "seniority": "wizard"}))

    with pytest.raises(DatasetError, match="case en-78: profile.json seniority"):
        load_case(folder)


def test_one_invalid_case_stops_the_loading(tmp_path: Path) -> None:
    make_case(tmp_path, "en-01")
    make_case(tmp_path, "en-02", expected_outcome="nope")

    with pytest.raises(DatasetError, match="case en-02"):
        load_cases(tmp_path)
