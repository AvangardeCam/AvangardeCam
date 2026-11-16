# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Stock window (CAM > Stock): what the stock's details show, in a window
like Contour tooling's, with a picture beside the fields (ui.field_pictures).

The size X × Y × Z of the block puts the model in its middle on that axis
(engine.stock_size); the six allowances can be typed one by one as in the
details. Each follows the other while typing; the stock changes on OK, in
one undo step.
"""

import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import op_zero
from avangardecam.model import stock as model_stock
from avangardecam.model import stock_size as model_stock_size
from avangardecam.ui import details, field_pictures, manual, window_fit

AXES = "XYZ"
# the allowances of each axis, below and above
_SIDES = (("x_neg_mm", "x_pos_mm"), ("y_neg_mm", "y_pos_mm"), ("z_neg_mm", "z_pos_mm"))


class StockDialog(QtWidgets.QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamStockDialog")
        self.setWindowTitle(tr("Stock"))
        self.job = job
        # on the active zero point's axes, or on the stock's own (engine.op_zero)
        edit = op_zero.stock_edit(job)
        self.model = edit.model
        self.own = edit.own
        self.current = current = edit.box
        self.fixed = current is None
        if current is None:
            current = _around(self.model, edit.bounds)

        box = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        box.addLayout(top)
        form = QtWidgets.QFormLayout()
        top.addLayout(form, 1)
        self.pictures = field_pictures.FieldPictures("stock_allowances.svg")
        top.addWidget(self.pictures, 0, QtCore.Qt.AlignTop)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        form.addRow(tr("Model") + ":", QtWidgets.QLabel(details.size_text(self.model)))

        self.sizes = []
        limit = 2 * model_stock.BoxStock.MAX_ALLOWANCE_MM
        for i, (axis, model_size) in enumerate(zip(AXES, self.model.size)):
            neg, pos = _SIDES[i]
            size = details.length_box(model_size + getattr(current, neg) + getattr(current, pos), 0.0, model_size + limit)
            size.setObjectName("AvangardeCamStockWindowSize" + axis)
            size.setToolTip(tr("The block's size; the model is put in its middle in {}.").format(axis))
            size.valueChanged.connect(lambda _value, i=i: self._size_typed(i))
            self.pictures.add(size, "stock_size.svg")
            form.addRow(tr("Size {}").format(axis) + ":", size)
            self.sizes.append(size)

        self.allowances = {}
        for name, label in details.StockView.ALLOWANCES:
            allowance = details.length_box(getattr(current, name))
            allowance.setObjectName("AvangardeCamStockWindow_" + name)
            allowance.valueChanged.connect(lambda _value, name=name: self._allowance_typed(name))
            self.pictures.add(allowance, "stock_allowances.svg")
            form.addRow(tr(label) + ":", allowance)
            self.allowances[name] = allowance

        self.summary = QtWidgets.QLabel()
        self.summary.setObjectName("AvangardeCamStockSummary")
        form.addRow(tr("Stock") + ":", self.summary)

        text = tr("The stock is the model's box plus an allowance on each side, in the setup's axes. Type the size of the block and the model is put in its middle on that axis (the same allowance on both sides), or type the allowances one by one. The stock changes on OK.")  # fmt: skip
        if self.fixed:
            fixed = QtWidgets.QLabel(tr("This stock was made in FreeCAD with a fixed size; OK replaces it by a box around the model."))  # fmt: skip
            fixed.setWordWrap(True)
            box.addWidget(fixed)
        if self.own:
            own = QtWidgets.QLabel(OWN_ZERO_NOTE())
            own.setObjectName("AvangardeCamStockOwnZero")
            own.setWordWrap(True)
            box.addWidget(own)
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamStockMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Stock"), text)
        box.addWidget(buttons)
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self._show_summary()
        self.sizes[0].setFocus()
        self.sizes[0].selectAll()

    # -- fields follow each other ----------------------------------------------

    def _size_typed(self, i):
        """The model in the middle of the size typed: both allowances of the axis."""
        size, model_size = self.sizes[i], self.model.size[i]
        self.message.setText("")
        if size.hasAcceptableInput():
            extra = _value(size) - model_size
            if extra >= -model_stock_size.TOLERANCE_MM:
                for name in _SIDES[i]:
                    _set(self.allowances[name], max(0.0, extra) / 2.0)
        self._show_summary()

    def _allowance_typed(self, name):
        """The size of the axis follows its allowances."""
        i = next(i for i, sides in enumerate(_SIDES) if name in sides)
        self.message.setText("")
        if all(self.allowances[n].hasAcceptableInput() for n in _SIDES[i]):
            _set(self.sizes[i], self.model.size[i] + sum(_value(self.allowances[n]) for n in _SIDES[i]))
        self._show_summary()

    def _show_summary(self):
        try:
            bounds = self.stock().bounds(self.model)
        except ValueError:
            self.summary.setText(details.NONE)
            return
        self.summary.setText(
            tr("{}, top Z {}, bottom Z {}").format(details.size_text(bounds), details.mm(bounds.z_max), details.mm(bounds.z_min))
        )

    # -- values ----------------------------------------------------------------

    def stock(self):
        """The BoxStock of the fields; ValueError when one does not hold a
        length or a size is smaller than the model."""
        for name, label in details.StockView.ALLOWANCES:
            if not self.allowances[name].hasAcceptableInput():
                raise ValueError(tr("{}: enter a length, for example 1 mm.").format(tr(label)))
        for axis, size, model_size in zip(AXES, self.sizes, self.model.size):
            if not size.hasAcceptableInput():
                raise ValueError(tr("Size {}: enter a length, for example 50 mm.").format(axis))
            if _value(size) - model_size < -model_stock_size.TOLERANCE_MM:
                raise ValueError(
                    tr("Size {} ({:g} mm) is smaller than the model ({:.2f} mm).").format(axis, _value(size), model_size)
                )
        return model_stock.BoxStock(**{name: _value(box) for name, box in self.allowances.items()}).validate()

    def accept(self):
        """Write the stock (one undo step); a refused value keeps the window open."""
        try:
            wanted = self.stock()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        if self.fixed or wanted != self.current:
            doc = self.job.Document
            doc.openTransaction(tr("Stock"))
            try:
                op_zero.set_stock(self.job, wanted)
            except (ValueError, cam.ProjectError) as exc:
                doc.abortTransaction()
                self.message.setText(str(exc))
                return
            doc.commitTransaction()
        super().accept()


def OWN_ZERO_NOTE():
    """Said where the stock is typed along its own zero point's axes."""
    return tr("The zero point is turned at an odd angle to the stock's own zero point: the sizes and allowances here are along the axes of the stock's own zero point (the default one it was made on).")  # fmt: skip


def _value(box):
    return float(box.property("rawValue"))


def _set(box, value):
    box.blockSignals(True)
    box.setProperty("rawValue", value)
    box.blockSignals(False)


def _around(model, bounds):
    """Allowances of a stock of another kind (a box of fixed size made in
    FreeCAD): how far its box reaches past the model, 0 where it does not."""
    return model_stock.BoxStock(
        max(0.0, model.x_min - bounds.x_min),
        max(0.0, bounds.x_max - model.x_max),
        max(0.0, model.y_min - bounds.y_min),
        max(0.0, bounds.y_max - model.y_max),
        max(0.0, model.z_min - bounds.z_min),
        max(0.0, bounds.z_max - model.z_max),
    )


def ask(job):
    """Open the window; True when OK changed (or kept) the stock."""
    try:
        dialog = StockDialog(job)
    except cam.ProjectError as exc:
        QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", str(exc))
        return False
    return bool(dialog.exec())
