from anki_addons_catalog.interface.web.rendering import best_values, render_description, render_markdown, render_readme


def test_ai_answer_escapes_raw_html() -> None:
    assert render_markdown('<img src="x.png">') == '<p>&lt;img src=&quot;x.png&quot;&gt;</p>\n'


def test_ai_answer_catalog_links_open_in_new_tab_on_request() -> None:
    assert render_markdown("[x](/addon/1)", new_tab=True) == '<p><a href="/addon/1" target="_blank">x</a></p>\n'
    assert render_markdown("[x](/addon/1)") == '<p><a href="/addon/1">x</a></p>\n'


def test_readme_without_repository_keeps_relative_urls() -> None:
    assert render_readme('<img src="x.png">', None, None) == '<img src="x.png">'


def test_description_is_sanitized_and_links_open_in_new_tab() -> None:
    html = render_description('<h2>T</h2><a href="https://x.org" onclick="alert(1)">x</a><script>alert(2)</script>')
    assert html == '<h2>T</h2><a href="https://x.org" target="_blank" rel="nofollow noopener noreferrer">x</a>'


def test_empty_description_renders_nothing() -> None:
    assert render_description(None) == ""
    assert render_description("") == ""


def test_best_values_of_a_fork_family() -> None:
    members = [
        {"compatibility": "unsupported", "maintenance": "active", "approval": 0.9, "rating": 50, "github_stars": 3},
        {"compatibility": "unknown", "maintenance": "active", "approval": 0.0, "rating": 0, "github_stars": None},
        {"compatibility": "supported", "maintenance": "active", "approval": 0.95, "rating": 900, "obsolete": True},
    ]
    assert best_values(members) == {"compatibility": "unknown", "approval": 0.9, "rating": 50}
    assert best_values(members[:1]) == {}
