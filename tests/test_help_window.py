"""
The help window: open_help lands on a page, links and history work, and an
example's Run reaches the console hook.
"""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from evans.ui import help


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    ran = []
    # Patched first, so teardown puts the module back as it found it.
    for name in ("_window", "_execute", "_busy"):
        monkeypatch.setattr(help, name, getattr(help, name))
    help._window = None
    help.set_console(ran.append, lambda: False)
    help.open_help("step")
    w = help.window()
    w.ran = ran
    yield w
    w.close()


def test_open_help_shows_the_topic(window):
    assert window.isVisible()
    assert window.topic == "step"
    assert "Step response" in window.browser.toPlainText()
    assert window.tree.currentItem().text(0) == "step"


def test_no_topic_opens_the_overview(window):
    help.open_help()
    assert window.topic == "index"


def test_one_window_however_often_it_is_asked(window):
    help.open_help("tf")
    assert help.window() is window


def test_links_and_history(window):
    window.browser.anchorClicked.emit(QUrl("help:impulse"))
    assert window.topic == "impulse"
    assert window.back.isEnabled() and not window.forward.isEnabled()
    window.back.click()
    assert window.topic == "step"
    window.forward.click()
    assert window.topic == "impulse"


def test_an_unknown_name_offers_the_search(window):
    help.open_help("my_own_function")
    assert "No page for my_own_function" in window.browser.toPlainText()
    assert window.search.text() == "my_own_function"


def test_run_sends_the_example_to_the_console(window):
    window.browser.anchorClicked.emit(QUrl("run:0"))
    assert window.ran == [help.pages.load("step").examples[0]]


def test_run_waits_while_the_console_is_busy(window):
    help.set_console(window.ran.append, lambda: True)
    window.browser.anchorClicked.emit(QUrl("run:0"))
    assert window.ran == []


def test_copy_puts_the_example_on_the_clipboard(window, app):
    window.browser.anchorClicked.emit(QUrl("copy:0"))
    assert app.clipboard().text() == help.pages.load("step").examples[0]


def test_no_run_link_without_a_console(window, monkeypatch):
    monkeypatch.setattr(help, "_execute", None)
    window.refresh()
    assert "Run" not in window.browser.toPlainText()
    assert "Copy" in window.browser.toPlainText()


def test_search_filters_the_tree_and_enter_opens(window):
    window.search.setText("bode")
    visible = [window.tree.topLevelItem(i).child(j).text(0)
               for i in range(window.tree.topLevelItemCount())
               for j in range(window.tree.topLevelItem(i).childCount())
               if not window.tree.topLevelItem(i).child(j).isHidden()]
    assert visible and "tf" not in visible
    window.search.returnPressed.emit()
    assert window.topic == "bode"
