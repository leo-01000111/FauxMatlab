"""
The help pages: one for every command, each well formed, each example runs.

A command added to ``api._GROUPS`` without a page fails here, as does a page
whose example no longer runs because the function under it changed.
"""

import pytest

from evans import help as pages
from evans.console.interpreter import Interpreter
from evans.help.render import to_html

FUNCTIONS = [n for names in pages.GROUPS.values() for n in names]
TOPICS = [*pages.GUIDES, *FUNCTIONS]


def test_no_topic_is_listed_twice():
    assert len(TOPICS) == len(set(TOPICS))


def test_every_console_command_is_listed():
    from evans.console import api
    for names in api._GROUPS.values():
        for name in names:
            assert pages.group_of(name) is not None, name


def test_no_page_is_left_out_of_the_index():
    on_disk = {p.stem for p in pages.PAGES.glob("*.md")}
    assert on_disk - set(TOPICS) == set()


@pytest.mark.parametrize("topic", TOPICS)
def test_page_exists_and_parses(topic):
    page = pages.load(topic)
    assert page is not None, f"no page for {topic}"
    if topic not in pages.GUIDES:
        assert page.title == topic


@pytest.mark.parametrize("topic", TOPICS)
def test_links_go_to_pages(topic):
    page = pages.load(topic)
    for target in page.links:
        assert target.removeprefix("help:") in TOPICS, \
            f"{topic} links to {target}, which has no page"


@pytest.mark.parametrize("topic", TOPICS)
def test_page_renders(topic):
    page = pages.load(topic)
    text = to_html(page)
    assert text.count('href="run:') == len(page.examples)


@pytest.mark.parametrize("topic", TOPICS)
def test_examples_run(topic, tmp_path, monkeypatch):
    """Each example, typed at a fresh console, runs without an error."""
    monkeypatch.chdir(tmp_path)
    for example in pages.load(topic).examples:
        result = Interpreter().command(example)
        assert result.ok, f"{topic}:\n{example}\n→ {result.error}"


def test_unknown_topics_have_no_page():
    assert pages.load("no_such_function") is None
    assert pages.load("../README") is None
    assert pages.load("") is None


def test_a_function_page_needs_its_sections():
    with pytest.raises(pages.PageError):
        pages.parse("# step\n\nStep response.\n\n## Syntax\n\n    step(G)\n",
                    "step")
