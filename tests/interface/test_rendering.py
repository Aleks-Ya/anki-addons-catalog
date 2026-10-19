from anki_addons_catalog.interface.web.rendering import render_markdown, render_readme


def test_ai_answer_escapes_raw_html() -> None:
    assert render_markdown('<img src="x.png">') == '<p>&lt;img src=&quot;x.png&quot;&gt;</p>\n'


def test_readme_without_repository_keeps_relative_urls() -> None:
    assert render_readme('<img src="x.png">', None, None) == '<img src="x.png">'
