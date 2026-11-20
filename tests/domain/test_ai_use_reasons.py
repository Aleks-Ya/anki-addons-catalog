from anki_addons_catalog.domain.models import ai_use_reasons

TOOLING = "The GitHub repository has files of AI coding tools: claude-code, cursor."
DECLARATION = "The description says that AI was used: vibe-coded."
FEATURES = "The addon has AI features."


def test_no_signal_gives_no_reason() -> None:
    assert ai_use_reasons(None, []) == []
    assert ai_use_reasons({}, ["statistics"]) == []


def test_each_signal_gives_its_reason() -> None:
    assert ai_use_reasons({"tooling": ["claude-code", "cursor"]}, []) == [TOOLING]
    assert ai_use_reasons({"declaration": ["vibe-coded"]}, []) == [DECLARATION]
    assert ai_use_reasons(None, ["statistics", "ai"]) == [FEATURES]


def test_all_signals_give_reasons_in_order() -> None:
    evidence = {"tooling": ["claude-code", "cursor"], "declaration": ["vibe-coded"]}
    assert ai_use_reasons(evidence, ["ai"]) == [TOOLING, DECLARATION, FEATURES]
