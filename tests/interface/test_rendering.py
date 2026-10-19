from anki_addons_catalog.interface.web.rendering import render_description, render_markdown, render_readme


def test_ai_answer_escapes_raw_html() -> None:
    assert render_markdown('<img src="x.png">') == '<p>&lt;img src=&quot;x.png&quot;&gt;</p>\n'


def test_readme_without_repository_keeps_relative_urls() -> None:
    assert render_readme('<img src="x.png">', None, None) == '<img src="x.png">'


def test_description_is_sanitized_and_links_open_in_new_tab() -> None:
    html = render_description('<h2>T</h2><a href="https://x.org" onclick="alert(1)">x</a><script>alert(2)</script>')
    assert html == '<h2>T</h2><a href="https://x.org" target="_blank" rel="nofollow noopener noreferrer">x</a>'


def test_empty_description_renders_nothing() -> None:
    assert render_description(None) == ""
    assert render_description("") == ""
