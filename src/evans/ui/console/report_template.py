"""
The report template's two stored levels, and the dialog that edits them.

The user's own template lives in ``QSettings`` (through :mod:`..persist`, so
the test suite writes to a scratch store); a live script's override is saved
in the script itself. Both are :class:`ReportTemplate` from
:mod:`evans.console.live.template`, where the default and the LaTeX they
produce are defined.
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...console.live.template import (
    DEFAULT,
    DOCUMENT_CLASSES,
    FONT_SIZES,
    FONTS,
    PAPERS,
    PLACEMENTS,
    ReportTemplate,
)
from .. import persist, theme
from ..design import TIGHT

#: Where the user's template is kept, as JSON of what differs from DEFAULT.
SETTINGS_KEY = "live/reportTemplate"


def user_template() -> ReportTemplate | None:
    """The user's saved template, or None when they have not made one."""
    raw = persist.settings().value(SETTINGS_KEY)
    if not raw:
        return None
    try:
        data = json.loads(str(raw))
    except ValueError:
        return None
    return ReportTemplate.from_dict(data) if isinstance(data, dict) else None


def set_user_template(template: ReportTemplate | None) -> None:
    store = persist.settings()
    if template is None:
        store.remove(SETTINGS_KEY)
    else:
        store.setValue(SETTINGS_KEY, json.dumps(template.to_dict()))


def _combo(items, editable: bool = False) -> QComboBox:
    box = QComboBox()
    box.addItems(list(items))
    box.setEditable(editable)
    return box


def _set_combo(box: QComboBox, value: str) -> None:
    index = box.findText(value)
    if index >= 0:
        box.setCurrentIndex(index)
    elif box.isEditable():
        box.setEditText(value)


def _text_box(placeholder: str, height: int = 110) -> QPlainTextEdit:
    box = QPlainTextEdit()
    box.setFont(theme.data_font(9.5))
    box.setPlaceholderText(placeholder)
    box.setLineWrapMode(QPlainTextEdit.NoWrap)
    box.setMinimumHeight(60)
    box.setMaximumHeight(height)
    return box


class ReportTemplateDialog(QDialog):
    """
    Edit the template of this live script or the user's default.

    The dialog edits two candidates and changes nothing until the caller
    reads :attr:`document_template` and :attr:`user_template` after it was
    accepted. A document "following the default" has no template of its own
    (None), and so changes with the user's template.
    """

    SCOPES = ("This live script", "My default (every live script)")

    def __init__(self, document_template: ReportTemplate | None,
                 user_template: ReportTemplate | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report template")
        self.document_template = document_template
        self.user_template = user_template
        self._scope = 0

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Applies to:"))
        self.scope = _combo(self.SCOPES)
        self.scope.setToolTip("The live script's own template is saved in the "
                              "script; the default is kept for every script "
                              "that has none of its own.")
        top.addWidget(self.scope)
        top.addStretch()
        layout.addLayout(top)
        self.follow = QCheckBox("This live script follows my default template")
        layout.addWidget(self.follow)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._page_tab(), "Page")
        self.tabs.addTab(self._title_tab(), "Title")
        self.tabs.addTab(self._header_tab(), "Header && footer")
        self.tabs.addTab(self._content_tab(), "Content")
        self.tabs.addTab(self._preamble_tab(), "Preamble")
        layout.addWidget(self.tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.reset = QPushButton("Evans default")
        self.reset.setToolTip("Put every field back to the template Evans "
                              "ships with")
        self.reset.clicked.connect(lambda: self._load(DEFAULT))
        buttons.addButton(self.reset, QDialogButtonBox.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.follow.setChecked(document_template is None)
        self._load(self._target())
        self._sync_enabled()
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.follow.toggled.connect(self._follow_toggled)
        self.resize(560, 470)

    # ── tabs ────────────────────────────────────────────────────

    def _page_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.document_class = _combo(DOCUMENT_CLASSES, editable=True)
        self.font_size = _combo(FONT_SIZES)
        self.paper = _combo(PAPERS)
        self.margin = QLineEdit()
        self.margin.setToolTip("Any LaTeX length: 2.5cm, 1in, 20mm")
        self.font = _combo(FONTS)
        form.addRow("Document class", self.document_class)
        form.addRow("Font size", self.font_size)
        form.addRow("Paper", self.paper)
        form.addRow("Margins", self.margin)
        form.addRow("Font", self.font)
        return page

    def _title_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.title_page = QCheckBox("Title on a page of its own")
        self.author = QLineEdit()
        self.author.setPlaceholderText("Author(s); \\and between names")
        self.date = QLineEdit()
        self.date.setPlaceholderText("No date — or \\today, or any text")
        self.contents = QCheckBox("Table of contents after the title")
        form.addRow(self.title_page)
        form.addRow("Author", self.author)
        form.addRow("Date", self.date)
        form.addRow(self.contents)
        note = QLabel("The first Title cell of the script is the title.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _header_tab(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setSpacing(TIGHT)
        for column, side in enumerate(("Left", "Centre", "Right"), start=1):
            grid.addWidget(QLabel(side), 0, column)
        self.header_footer: dict[str, QLineEdit] = {}
        for row, where in enumerate(("header", "footer"), start=1):
            grid.addWidget(QLabel(where.capitalize()), row, 0)
            for column, side in enumerate(("left", "center", "right"),
                                          start=1):
                edit = QLineEdit()
                self.header_footer[f"{where}_{side}"] = edit
                grid.addWidget(edit, row, column)
        note = QLabel("LaTeX: \\thepage is the page number, \\leftmark the "
                      "current section. All empty: page numbers centred at "
                      "the foot, as LaTeX does by default.")
        note.setWordWrap(True)
        grid.addWidget(note, 3, 0, 1, 4)
        grid.setRowStretch(4, 1)
        return page

    def _content_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.number_sections = QCheckBox("Number the sections (1, 1.1, …)")
        self.show_code = QCheckBox("Show code cells as listings")
        self.show_output = QCheckBox("Show what code cells print")
        self.latex_text = QCheckBox("Text cells are LaTeX")
        self.latex_text.setToolTip(
            "On: LaTeX in text cells reaches the document as written "
            "(\\ref, \\cite, environments), alongside the **bold** / *italic* "
            "marks.\nOff: text cells are plain prose; every special "
            "character is printed as itself.")
        self.figure_width = QLineEdit()
        self.figure_width.setToolTip("Width of each figure: 0.8\\linewidth, "
                                     "12cm …")
        self.placement = _combo(PLACEMENTS, editable=True)
        self.placement.setToolTip("H: right under the code that drew it.\n"
                                  "htbp: wherever LaTeX finds room.")
        for box in (self.number_sections, self.show_code, self.show_output,
                    self.latex_text):
            form.addRow(box)
        form.addRow("Figure width", self.figure_width)
        form.addRow("Figure placement", self.placement)
        return page

    def _preamble_tab(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.addWidget(QLabel("Added to the preamble (packages, macros):"))
        self.extra_preamble = _text_box("\\usepackage{siunitx}")
        column.addWidget(self.extra_preamble)
        row = QHBoxLayout()
        self.raw = QCheckBox("Write the whole preamble by hand")
        self.raw.setToolTip("Everything before \\begin{document}. The page, "
                            "font and header settings then do nothing.")
        row.addWidget(self.raw)
        row.addStretch()
        self.generate = QPushButton("Start from the generated one")
        self.generate.clicked.connect(self._fill_raw)
        row.addWidget(self.generate)
        column.addLayout(row)
        self.raw_preamble = _text_box("\\documentclass{article} …", 200)
        column.addWidget(self.raw_preamble, stretch=1)
        self.raw.toggled.connect(self._raw_toggled)
        return page

    # ── form ↔ template ─────────────────────────────────────────

    def _load(self, template: ReportTemplate) -> None:
        t = template
        _set_combo(self.document_class, t.document_class)
        _set_combo(self.font_size, t.font_size)
        _set_combo(self.paper, t.paper)
        self.margin.setText(t.margin)
        _set_combo(self.font, t.font)
        self.title_page.setChecked(t.title_page)
        self.author.setText(t.author)
        self.date.setText(t.date)
        self.contents.setChecked(t.contents)
        for key, edit in self.header_footer.items():
            edit.setText(getattr(t, key))
        self.number_sections.setChecked(t.number_sections)
        self.show_code.setChecked(t.show_code)
        self.show_output.setChecked(t.show_output)
        self.latex_text.setChecked(t.latex_text)
        self.figure_width.setText(t.figure_width)
        _set_combo(self.placement, t.figure_placement)
        self.extra_preamble.setPlainText(t.extra_preamble)
        self.raw.blockSignals(True)
        self.raw.setChecked(bool(t.raw_preamble.strip()))
        self.raw.blockSignals(False)
        self.raw_preamble.setPlainText(t.raw_preamble)
        self.raw_preamble.setEnabled(self.raw.isChecked())

    def form_template(self) -> ReportTemplate:
        """The template the fields describe."""
        return ReportTemplate(
            document_class=self.document_class.currentText().strip()
            or "article",
            font_size=self.font_size.currentText(),
            paper=self.paper.currentText(),
            margin=self.margin.text().strip() or DEFAULT.margin,
            font=self.font.currentText(),
            title_page=self.title_page.isChecked(),
            author=self.author.text(),
            date=self.date.text(),
            contents=self.contents.isChecked(),
            **{key: edit.text() for key, edit in self.header_footer.items()},
            number_sections=self.number_sections.isChecked(),
            show_code=self.show_code.isChecked(),
            show_output=self.show_output.isChecked(),
            latex_text=self.latex_text.isChecked(),
            figure_width=self.figure_width.text().strip()
            or DEFAULT.figure_width,
            figure_placement=self.placement.currentText().strip() or "H",
            extra_preamble=self.extra_preamble.toPlainText(),
            raw_preamble=self.raw_preamble.toPlainText()
            if self.raw.isChecked() else "",
        )

    # ── scope ───────────────────────────────────────────────────

    def _target(self) -> ReportTemplate:
        """What the form shows for the current scope."""
        if self._scope == 0 and self.document_template is not None:
            return self.document_template
        return self.user_template or DEFAULT

    def _store(self) -> None:
        """The form into the template of the current scope."""
        if self._scope == 1:
            self.user_template = self.form_template()
        elif not self.follow.isChecked():
            self.document_template = self.form_template()

    def _scope_changed(self, index: int) -> None:
        self._store()
        self._scope = index
        self._load(self._target())
        self._sync_enabled()

    def _follow_toggled(self, follow: bool) -> None:
        if follow:
            self.document_template = None
        else:
            # Start the script's own from what it followed until now.
            self.document_template = (self.user_template or DEFAULT).copy()
        self._load(self._target())
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        document = self._scope == 0
        self.follow.setVisible(document)
        editable = not (document and self.follow.isChecked())
        self.tabs.setEnabled(editable)
        self.reset.setEnabled(editable)

    def _raw_toggled(self, on: bool) -> None:
        self.raw_preamble.setEnabled(on)
        if on and not self.raw_preamble.toPlainText().strip():
            self._fill_raw()

    def _fill_raw(self) -> None:
        template = self.form_template().copy(raw_preamble="")
        self.raw_preamble.setPlainText(template.generated_preamble())
        self.raw.setChecked(True)

    def commit(self) -> None:
        """Take what the form shows into :attr:`document_template` /
        :attr:`user_template`. Accepting the dialog does it."""
        self._store()

    def accept(self) -> None:
        self.commit()
        super().accept()
