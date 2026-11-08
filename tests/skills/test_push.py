import sonar


def test_analyzed_sha() -> None:
    branches = {"branches": [{"name": "master", "isMain": True},
                             {"name": "main", "isMain": False, "commit": {"sha": "abc"}}]}
    assert sonar.analyzed_sha(branches) == "abc"
    assert sonar.analyzed_sha({"branches": [{"name": "main"}]}) is None


def test_failed_conditions() -> None:
    status = {"projectStatus": {"status": "ERROR", "conditions": [
        {"status": "OK", "metricKey": "new_security_rating", "comparator": "GT", "errorThreshold": "1",
         "actualValue": "1"},
        {"status": "ERROR", "metricKey": "new_coverage", "comparator": "LT", "errorThreshold": "80",
         "actualValue": "75.0"}]}}
    assert sonar.failed_conditions(status) == ["new_coverage 75.0 (threshold LT 80)"]


def test_findings_newest_first() -> None:
    issues = {"issues": [
        {"rule": "python:S1192", "severity": "MINOR", "component": "Aleks-Ya_anki-addons-catalog:src/a.py",
         "line": 3, "message": "Define a constant", "creationDate": "2026-10-01T10:00:00+0000"},
        {"rule": "python:S3776", "severity": "CRITICAL", "component": "Aleks-Ya_anki-addons-catalog:src/b.py",
         "message": "Reduce complexity", "creationDate": "2026-11-08T10:00:00+0000"}]}
    hotspots = {"hotspots": [
        {"ruleKey": "python:S5332", "vulnerabilityProbability": "LOW",
         "component": "Aleks-Ya_anki-addons-catalog:src/c.py", "line": 7, "message": "Use https",
         "creationDate": "2026-11-01T10:00:00+0000"}]}
    assert sonar.findings(issues, hotspots) == [
        "2026-11-08 CRITICAL python:S3776 src/b.py Reduce complexity",
        "2026-11-01 hotspot/LOW python:S5332 src/c.py:7 Use https",
        "2026-10-01 MINOR python:S1192 src/a.py:3 Define a constant",
    ]
