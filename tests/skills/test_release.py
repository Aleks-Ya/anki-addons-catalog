import pytest
import verify
import versions


@pytest.mark.parametrize(("current", "tag", "expected"), [
    ("0.7.0.dev0", "v0.6.0", {"major": "1.0.0", "minor": "0.7.0", "patch": "0.6.1"}),
    ("1.2.2", "v1.2.1", {"major": "2.0.0", "minor": "1.3.0", "patch": "1.2.3"}),
    ("0.1.0.dev0", "", {"major": "1.0.0", "minor": "0.2.0", "patch": "0.1.1"}),
])
def test_candidates(current: str, tag: str, expected: dict[str, str]) -> None:
    assert versions.candidates(current, tag) == expected


@pytest.mark.parametrize(("version", "tag", "problem"), [
    ("0.6.1", "v0.6.0", None),
    ("0.10.0", "v0.9.0", None),  # compared as numbers, not as text
    ("1.0.0", "", None),
    ("0.6.0", "v0.6.0", "0.6.0 is not higher than the last release v0.6.0"),
    ("0.5.9", "v0.6.0", "0.5.9 is not higher than the last release v0.6.0"),
    ("1.0", "v0.6.0", "'1.0' is not a plain X.Y.Z version"),
    ("1.0.0.dev0", "v0.6.0", "'1.0.0.dev0' is not a plain X.Y.Z version"),
])
def test_invalid(version: str, tag: str, problem: str | None) -> None:
    assert versions.invalid(version, tag) == problem


def test_next_dev() -> None:
    assert verify.next_dev("0.3.1") == "0.4.0.dev0"
    assert verify.next_dev("1.9.0") == "1.10.0.dev0"
