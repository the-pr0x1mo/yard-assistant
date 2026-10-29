"""Text-only extraction evaluation. No imports from the API, Whisper or database."""
import argparse
import json
import sys
from pathlib import Path

from app import services
from app.schemas import HiveInspectionPayload
from app.terminology import load_terminology

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "sr_inspections_v1.json"


def validate_case(case: dict) -> dict:
    if not isinstance(case, dict) or set(case) - {"id", "transcript", "expected", "note_contains"}:
        raise ValueError("Invalid fixture case")
    if not isinstance(case.get("id"), str) or not case["id"].strip():
        raise ValueError("Case requires a nonempty id")
    if not isinstance(case.get("transcript"), str) or not case["transcript"].strip():
        raise ValueError("Case requires a nonempty transcript")
    if "expected" in case:
        HiveInspectionPayload.model_validate(case["expected"])
    notes = case.get("note_contains", [])
    if not isinstance(notes, list) or any(not isinstance(n, str) or not n for n in notes):
        raise ValueError("note_contains must be a list of source excerpts")
    if any(n.casefold() not in case["transcript"].casefold() for n in notes):
        raise ValueError("Required notes must occur in the original transcript")
    return case


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"version", "cases"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["cases"], list) or not data["cases"]):
        raise ValueError("Expected version 1 fixture file with nonempty cases")
    cases = [validate_case(c) for c in data["cases"]]
    if any("expected" not in c for c in cases) or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Fixtures require expected results and unique ids")
    return cases


def compare_payload(actual: HiveInspectionPayload | None, case: dict) -> dict:
    """Closed-world facts: unspecified structured fields must remain null."""
    expected = HiveInspectionPayload.model_validate(case["expected"]).model_dump()
    actual = actual.model_dump() if actual is not None else {
        section: dict.fromkeys(fields) for section, fields in expected.items()}
    missing, wrong, unsupported = [], [], []
    matched_facts = expected_facts = 0
    for section, fields in expected.items():
        for field, wanted in fields.items():
            if (section, field) in {("inspection", "note"), ("hive", "notes")}:
                continue
            observed = actual[section][field]
            path = f"{section}.{field}"
            if wanted is not None:
                expected_facts += 1
            if observed == wanted:
                matched_facts += wanted is not None
            elif observed is None:
                missing.append({"field": path, "expected": wanted})
            elif wanted is None:
                unsupported.append({"field": path, "actual": observed})
            else:
                wrong.append({"field": path, "expected": wanted, "actual": observed})
    note = actual["inspection"]["note"] or ""
    missing_notes = [excerpt for excerpt in case.get("note_contains", []) if excerpt.casefold() not in note.casefold()]
    return {"passed": not (missing or wrong or unsupported or missing_notes),
            "missing_facts": missing, "wrong_values": wrong, "unsupported_extractions": unsupported,
            "missing_notes": missing_notes, "expected_facts": expected_facts, "matched_facts": matched_facts}


def summarize(results: list[dict]) -> dict:
    scored = [r["comparison"] for r in results if r.get("comparison") is not None]
    expected = sum(c["expected_facts"] for c in scored)
    matched = sum(c["matched_facts"] for c in scored)
    return {"cases": len(results), "extraction_failures": sum(r["status"] == "failed" for r in results),
            "compared_cases": len(scored), "passed_cases": sum(c["passed"] for c in scored),
            "expected_facts": expected, "matched_facts": matched,
            "fact_recall": matched / expected if expected else None,
            "missing_facts": sum(len(c["missing_facts"]) for c in scored),
            "wrong_values": sum(len(c["wrong_values"]) for c in scored),
            "unsupported_extractions": sum(len(c["unsupported_extractions"]) for c in scored),
            "missing_notes": sum(len(c["missing_notes"]) for c in scored)}


def replay(raw, transcript: str) -> HiveInspectionPayload:
    # Exercise the application's JSON parsing, strict validation and hive ID logic.
    return services.parse_payload(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False), transcript)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="Inspection transcript")
    source.add_argument("--text-file", type=Path, help="UTF-8 transcript file; - reads stdin")
    source.add_argument("--fixtures", type=Path, help=f"Fixture file (default: {FIXTURE_PATH.name})")
    parser.add_argument("--expected", type=Path, help="Expected payload JSON for --text/--text-file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Call the configured Ollama, without persistence")
    mode.add_argument("--responses", type=Path, help="Replay JSON mapping of case ids to raw responses/payloads")
    parser.add_argument("--prompt-version", choices=services.PROMPT_VERSIONS, default=services.PROMPT_VERSION)
    parser.add_argument("--compare", action="store_true", help="Run live v2 and v2.1 on the same cases")
    parser.add_argument("--case", action="append", dest="case_ids", help="Select fixture id; repeatable")
    args = parser.parse_args(argv)
    if args.compare and not args.live:
        parser.error("--compare requires --live")
    if args.expected and args.text is None and args.text_file is None:
        parser.error("--expected requires --text or --text-file")
    try:
        dictionary = load_terminology()
        if args.text is not None or args.text_file is not None:
            transcript = args.text if args.text is not None else (
                sys.stdin.read() if str(args.text_file) == "-" else args.text_file.read_text(encoding="utf-8"))
            case = {"id": "text", "transcript": transcript}
            if args.expected:
                case["expected"] = json.loads(args.expected.read_text(encoding="utf-8"))
            cases = [validate_case(case)]
        else:
            cases = load_cases(args.fixtures or FIXTURE_PATH)
        if args.case_ids:
            if set(args.case_ids) - {c["id"] for c in cases}:
                raise ValueError("Unknown case id")
            cases = [c for c in cases if c["id"] in args.case_ids]
        responses = json.loads(args.responses.read_text(encoding="utf-8")) if args.responses else None
        if args.responses and (not isinstance(responses, dict) or any(c["id"] not in responses for c in cases)):
            raise ValueError("Responses must map every selected case id to a response")
        versions = services.PROMPT_VERSIONS if args.compare else (args.prompt_version,)
        report = {"mode": "live" if args.live else "replay" if responses is not None else "validate",
                  "terminology_version": dictionary.version, "terminology_sha256": dictionary.digest, "runs": []}
        exit_code = 0
        for version in versions:
            results = []
            for case in cases:
                row = {"id": case["id"], "status": "validated", "comparison": None,
                       "metadata": {"model": None, "prompt_version": version,
                                    "prompt_eval_count": None, "eval_count": None, "duration_ms": None}}
                payload = None
                if args.live:
                    result = services.ollama_extract(case["transcript"], prompt_version=version)
                    row.update(status=result.status, error=result.error.model_dump() if result.error else None)
                    row["metadata"].update(result.metadata)
                    row["model_response"] = result.model_response
                    payload = result.payload
                elif responses is not None:
                    # A replay is a parser/comparator check, never a measurement of model accuracy.
                    try:
                        payload = replay(responses[case["id"]], case["transcript"])
                        row["status"] = "completed"
                    except (ValueError, TypeError):
                        row.update(status="failed", error={"code": "invalid_replay", "message": "Response failed application validation"})
                else:
                    row["metadata"]["system_prompt_chars"] = len(services.build_system_prompt(case["transcript"], version))
                if payload is not None:
                    row["payload"] = payload.model_dump()
                    if "expected" in case:
                        row["comparison"] = compare_payload(payload, case)
                elif row["status"] == "failed" and "expected" in case:
                    # Failed requests count as missing facts; never silently drop them from recall.
                    row["comparison"] = compare_payload(None, case)
                    row["comparison"]["passed"] = False
                if row["status"] == "failed" or (row["comparison"] and not row["comparison"]["passed"]):
                    exit_code = 1
                results.append(row)
            report["runs"].append({"prompt_version": version, "results": results, "summary": summarize(results)})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
