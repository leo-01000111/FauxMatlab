"""
The documentation site builds from the current code.

The reference pages are generated from the console's command groups, the
block registry and the lessons, so a command, block or lesson added without
what the site needs to describe it fails here rather than on the Pages build.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build_module():
    spec = importlib.util.spec_from_file_location(
        "evans_site_build", ROOT / "site" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_site_builds_with_every_command_block_and_lesson(tmp_path):
    from evans.console import api
    from evans.core.lessons import all_lessons
    from evans.sim import block_types

    build = _build_module()
    stats = build.build(tmp_path)

    assert stats["undocumented"] == [], "commands with no docstring"
    assert stats["failed_claims"] == []
    for file, *_ in build.PAGES:
        assert (tmp_path / file).is_file(), file

    commands = (tmp_path / "commands.html").read_text(encoding="utf-8")
    for names in api._GROUPS.values():
        for name in names:
            assert f'id="{name}"' in commands, name

    blocks = (tmp_path / "blocks.html").read_text(encoding="utf-8")
    for name in block_types():
        assert f'id="{name}"' in blocks, name

    lessons = (tmp_path / "lessons.html").read_text(encoding="utf-8")
    for lesson in all_lessons():
        assert f'id="{lesson.key}"' in lessons, lesson.key


def test_hand_written_pages_link_only_to_pages_that_exist(tmp_path):
    import re

    build = _build_module()
    build.build(tmp_path)
    pages = {file for file, *_ in build.PAGES}
    for file in pages:
        text = (tmp_path / file).read_text(encoding="utf-8")
        for target in re.findall(r'href="([a-z-]+\.html)', text):
            assert target in pages, f"{file} links to missing {target}"
        for asset in re.findall(r'(?:src|href)="(assets/[^"#]+)"', text):
            assert (tmp_path / asset).is_file(), f"{file} uses missing {asset}"


def test_patch_notes_cover_the_current_version_and_carry_the_issue_form(tmp_path):
    from evans import __version__

    build = _build_module()
    build.build(tmp_path)
    notes = (tmp_path / "patch-notes.html").read_text(encoding="utf-8")
    assert f'id="v{__version__}"' in notes, "no patch notes for this version"
    assert 'action="https://formspree.io/f/xppqgygl"' in notes
    for file in ("index.html", "install.html"):
        assert 'href="patch-notes.html#report"' in (tmp_path / file).read_text(encoding="utf-8")
