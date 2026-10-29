import json
import subprocess
import sys

import pytest

from app import services
from app.evaluate import FIXTURE_PATH, compare_payload, load_cases, main, replay
from app.schemas import HiveInspectionPayload

CASES = load_cases(FIXTURE_PATH)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_fixture_contract_through_application_parser_and_mocked_request(case, ollama):
    # These are plumbing regressions with known responses, not model accuracy tests.
    expected = dict(case["expected"])
    expected["inspection"] = dict(expected["inspection"], note="; ".join(case.get("note_contains", [])) or None)
    request, _ = ollama(json.dumps(expected, ensure_ascii=False))
    original = case["transcript"]
    result = services.ollama_extract(original)
    assert result.status == "completed"
    assert compare_payload(result.payload, case)["passed"]
    body = request.call_args.kwargs["json"]
    assert body["prompt"].endswith(original)
    assert body["system"] == services.build_system_prompt(original)
    assert result.metadata["prompt_version"] == "hive_semantics_v2_1"
    assert result.metadata["terminology_version"] == 2


def test_previous_live_fixture_does_not_force_ambiguous_brood_or_eggs():
    case = CASES[0]
    assert case["expected"]["inspection"]["capped_brood"] is None
    assert case["expected"]["inspection"]["eggs_seen"] is None
    assert case["transcript"].endswith("temperament mirana.")


def test_comparator_reports_missing_wrong_unsupported_and_lost_notes():
    case = CASES[0]
    actual = HiveInspectionPayload.model_validate({"hive": {"hive_id": "H1"}, "inspection": {
        "brood_frames": 2, "open_brood": 1, "behavior": "mirne", "capped_brood": 1, "eggs_seen": 0}})
    comparison = compare_payload(actual, case)
    assert {v["field"] for v in comparison["missing_facts"]} == {"inspection.honey_frames", "inspection.queen_seen"}
    assert comparison["wrong_values"] == [{"field": "inspection.brood_frames", "expected": 3, "actual": 2}]
    assert {v["field"] for v in comparison["unsupported_extractions"]} == {"inspection.capped_brood", "inspection.eggs_seen"}
    assert comparison["missing_notes"] == case["note_contains"]
    assert comparison["matched_facts"] == 3
    assert not comparison["passed"]


def test_default_cli_validates_fixtures_without_http_or_persistence(monkeypatch, capsys, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline CLI must not call HTTP")
    monkeypatch.setattr(services.requests, "post", forbidden)
    missing_db = tmp_path / "never-created.sqlite"
    monkeypatch.setenv("DB_PATH", str(missing_db))
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "validate"
    assert report["runs"][0]["summary"]["cases"] == len(CASES)
    assert report["runs"][0]["summary"]["compared_cases"] == 0
    assert report["runs"][0]["summary"]["fact_recall"] is None
    assert not missing_db.exists()


def test_cli_replay_is_explicit_and_uses_strict_application_validation(tmp_path, capsys):
    path = tmp_path / "responses.json"
    path.write_text(json.dumps({"explicit_negation": CASES[2]["expected"]}))
    assert main(["--case", "explicit_negation", "--responses", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "replay"
    summary = report["runs"][0]["summary"]
    assert summary["passed_cases"] == 1 and summary["fact_recall"] == 1
    metadata = report["runs"][0]["results"][0]["metadata"]
    assert metadata["model"] is None and metadata["eval_count"] is None
    path.write_text(json.dumps({"explicit_negation": {"hive": {"hive_id": "H3"}, "inspection": {"queen_seen": True}}}))
    assert main(["--case", "explicit_negation", "--responses", str(path)]) == 1
    report = json.loads(capsys.readouterr().out)
    summary = report["runs"][0]["summary"]
    assert summary["extraction_failures"] == 1
    assert summary["fact_recall"] == 0
    assert summary["missing_facts"] == 6


@pytest.mark.parametrize("responses", [None, [], {}, {"wrong_case": {}}])
def test_cli_rejects_missing_or_invalid_replay_responses(tmp_path, responses):
    path = tmp_path / "responses.json"
    path.write_text(json.dumps(responses))
    with pytest.raises(SystemExit) as exc:
        main(["--case", "explicit_negation", "--responses", str(path)])
    assert exc.value.code == 2


def test_cli_live_text_uses_application_extractor_and_reports_metadata(ollama, capsys, tmp_path, monkeypatch):
    expected = CASES[2]["expected"]
    request, _ = ollama(json.dumps(expected))
    expected_file = tmp_path / "expected.json"
    expected_file.write_text(json.dumps(expected))
    db_path = tmp_path / "do-not-open.sqlite"
    db_path.write_bytes(b"untouched sentinel")
    monkeypatch.setenv("DB_PATH", str(db_path))
    assert main(["--text", CASES[2]["transcript"], "--expected", str(expected_file), "--live"]) == 0
    report = json.loads(capsys.readouterr().out)
    row = report["runs"][0]["results"][0]
    assert row["comparison"]["passed"]
    assert row["metadata"]["model"] == "fixture"
    assert row["metadata"]["prompt_eval_count"] == 50
    assert row["metadata"]["eval_count"] == 25
    assert row["metadata"]["duration_ms"] >= 0
    assert row["metadata"]["eval_duration"] == 800
    assert request.call_count == 1
    assert db_path.read_bytes() == b"untouched sentinel"


def test_cli_compare_uses_same_model_and_original_v2(ollama, capsys):
    request, _ = ollama(json.dumps(CASES[2]["expected"]))
    assert main(["--case", "explicit_negation", "--live", "--compare"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [r["prompt_version"] for r in report["runs"]] == list(services.PROMPT_VERSIONS)
    baseline, candidate = [call.kwargs["json"] for call in request.call_args_list]
    assert baseline["system"] == services.read_prompt("hive_semantics_v2")
    assert candidate["system"] == services.build_system_prompt(CASES[2]["transcript"])
    assert baseline["model"] == candidate["model"] == services.OLLAMA_MODEL
    assert baseline["prompt"] == candidate["prompt"]
    assert baseline["options"] == candidate["options"] == {"temperature": 0, "seed": 42}


def test_cli_failure_counts_all_expected_facts_including_unknown_hive(ollama, capsys):
    import requests
    ollama(error=requests.ConnectionError())
    assert main(["--case", "sparse_no_identifier", "--live"]) == 1
    report = json.loads(capsys.readouterr().out)
    summary = report["runs"][0]["summary"]
    assert summary["fact_recall"] == 0
    assert summary["expected_facts"] == summary["missing_facts"] == 1
    assert report["runs"][0]["results"][0]["metadata"]["eval_count"] is None


def test_cli_text_file_and_stdin(tmp_path, capsys, monkeypatch):
    import io
    path = tmp_path / "text.txt"
    path.write_text("Košnica 1. Ima larvi.")
    assert main(["--text-file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "validate"
    monkeypatch.setattr(sys, "stdin", io.StringIO("Košnica 2. Nema larvi."))
    assert main(["--text-file", "-"]) == 0


@pytest.mark.parametrize("args", [["--compare"], ["--case", "missing"], ["--expected", "missing.json"],
                                 ["--prompt-version", "../../secrets"], ["--text", " "]])
def test_cli_rejects_invalid_arguments(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize("document", [
    {"version": 1, "cases": []}, {"version": 2, "cases": CASES},
    {"version": 1, "cases": [CASES[0], CASES[0]]},
    {"version": 1, "cases": [{"id": "bad", "transcript": "abc", "expected": {"hive": {"hive_id": "H1"}, "inspection": {"behavior": "ljute"}}}]},
    {"version": 1, "cases": [dict(CASES[0], note_contains=["not in transcript"])]},
])
def test_invalid_fixture_files(tmp_path, document):
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_cases(path)


def test_cli_module_runs_without_loading_api_audio_or_database():
    code = "from app.evaluate import main; import sys; main(['--text', 'Matica viđena.']); assert not {'app.main', 'app.db', 'app.pipeline', 'faster_whisper'} & sys.modules.keys()"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_replay_rejects_wrapped_json_and_analysis_fields():
    with pytest.raises(ValueError):
        replay('```json\n{}\n```', "")
    with pytest.raises(ValueError):
        replay({"hive": {"hive_id": "H1"}, "inspection": {"health_score": 100}}, "Košnica 1.")


def test_absent_flags_hallucinated_zeros_are_reported_and_raw_output_is_retained(ollama):
    case = next(c for c in CASES if c["id"] == "absent_flags")
    unsupported = {"open_brood": 0, "queen_seen": 0}
    raw = json.dumps({"hive": case["expected"]["hive"],
                      "inspection": dict(case["expected"]["inspection"], **unsupported)})
    ollama(raw)
    result = services.ollama_extract(case["transcript"])
    assert result.model_response == raw
    comparison = compare_payload(result.payload, case)
    assert not comparison["passed"]
    assert comparison["unsupported_extractions"] == [
        {"field": "inspection.open_brood", "actual": 0},
        {"field": "inspection.queen_seen", "actual": 0}]
    assert comparison["missing_facts"] == comparison["wrong_values"] == []


@pytest.mark.parametrize("wrong_facts", [
    {"queen_seen": 0}, {"queen_seen": 1}, {"eggs_seen": 1}, {"capped_brood": 1},
])
def test_log2_unclear_asr_is_not_scored_as_a_confirmed_observation(wrong_facts):
    case = next(c for c in CASES if c["id"] == "log2_live_asr")
    raw = {"hive": {"hive_id": None}, "inspection": {
        **case["expected"]["inspection"], **wrong_facts,
        "note": "; ".join(case["note_contains"])}}
    actual = replay(raw, case["transcript"])
    assert actual.hive.hive_id == "H3"
    comparison = compare_payload(actual, case)
    assert not comparison["passed"]
    assert comparison["unsupported_extractions"] == [
        {"field": f"inspection.{field}", "actual": value} for field, value in wrong_facts.items()]


def test_cli_replay_reports_unrelated_negative_hallucinations(tmp_path, capsys):
    case = next(c for c in CASES if c["id"] == "absent_flags")
    raw = {"hive": case["expected"]["hive"], "inspection": {
        **case["expected"]["inspection"], "open_brood": 0, "queen_seen": 0}}
    path = tmp_path / "responses.json"
    path.write_text(json.dumps({"absent_flags": raw}))
    assert main(["--case", "absent_flags", "--responses", str(path)]) == 1
    row = json.loads(capsys.readouterr().out)["runs"][0]["results"][0]
    assert row["comparison"]["unsupported_extractions"] == [
        {"field": "inspection.open_brood", "actual": 0},
        {"field": "inspection.queen_seen", "actual": 0}]
