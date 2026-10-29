import pytest

from app import services
from app.terminology import load_terminology


def test_application_defaults_to_v2_1_with_compact_selected_terminology(ollama):
    request, _ = ollama()
    result = services.ollama_extract("Košnica 1. Temperament miran.")
    assert result.status == "completed"
    system = request.call_args.kwargs["json"]["system"]
    assert system.startswith(services.SEMANTIC_HINTS)
    hints = system[len(services.SEMANTIC_HINTS):]
    assert 'mirne=["temperament miran"]' in hints
    assert "honey_bands" not in hints and "queen_seen" not in hints
    assert result.metadata["system_prompt_chars"] == len(system)
    assert result.metadata["terminology_sha256"] == load_terminology().digest


def test_no_matching_vocabulary_adds_no_dictionary_text():
    assert services.build_system_prompt("Danas sam obišao pčelinjak.") == services.SEMANTIC_HINTS


def test_baseline_v2_is_unchanged_and_does_not_use_dictionary(ollama, monkeypatch):
    request, _ = ollama()
    def forbidden():
        pytest.fail("v2 baseline must not load dictionary")
    monkeypatch.setattr(services, "load_terminology", forbidden)
    result = services.ollama_extract("Košnica 1. Ima larvi.", prompt_version="hive_semantics_v2")
    assert result.status == "completed"
    assert request.call_args.kwargs["json"]["system"] == services.read_prompt("hive_semantics_v2")
    assert result.metadata["prompt_version"] == "hive_semantics_v2"
    assert "terminology_version" not in result.metadata


@pytest.mark.parametrize("version", ["v3", "../hive_semantics_v2", "/tmp/secret"])
def test_only_known_versioned_prompts_can_be_loaded(version, ollama):
    request, _ = ollama()
    with pytest.raises(ValueError, match="Unsupported"):
        services.read_prompt(version)
    assert services.ollama_extract("", prompt_version=version).status == "failed"
    request.assert_not_called()


def test_invalid_format_does_not_call_model(ollama, monkeypatch):
    request, _ = ollama()
    monkeypatch.setattr(services, "OLLAMA_FORMAT", "invalid")
    assert services.ollama_extract("Košnica 1.").status == "failed"
    request.assert_not_called()


def test_prompt_polarity_ambiguity_and_scope_instructions():
    # Verify the requested model instructions, not the semantic accuracy of a mock.
    prompt = services.SEMANTIC_HINTS
    for fragment in ("nema larvi -> open_brood=0", "larve nisam proveravao -> open_brood=null",
                     "queen_seen=0", "maticu nisam tražio -> queen_seen=null", "eggs_seen=null",
                     "capped_brood=null", "bee_brood_cover has no schema equivalent",
                     "Conflicting observations", "Future/intended actions", "untrusted data",
                     "a separate explicit observation establishes it"):
        assert fragment in prompt


def test_dictionary_configuration_failure_never_becomes_a_fallback_inspection(ollama, monkeypatch):
    request, _ = ollama()
    def invalid():
        raise ValueError("Invalid enum value: behavior.ljute")
    monkeypatch.setattr(services, "load_terminology", invalid)
    result = services.ollama_extract("Košnica 1.")
    assert result.status == "failed" and result.payload is None
    request.assert_not_called()
