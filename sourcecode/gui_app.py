from __future__ import annotations

import os
from typing import List, Tuple

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sourcecode.spectra_math import (
    FitResult,
    ProcessedSpectra,
    SpectraDataset,
    apply_validity_and_filter,
    detect_initial_peaks,
    expand_peaks_for_hidden_doublets,
    expand_peaks_with_derivative_mode,
    expand_peaks_with_local_aic,
    fit_spectrum,
    load_spectra_csv,
    peaks_summary_dataframe,
    spectrum_result_dataframe,
)


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self) -> None:
        self.figure = Figure(figsize=(8, 5), tight_layout=True)
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)


class SpectraMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Spectra Analysis")
        self.resize(1400, 900)

        self.dataset: SpectraDataset | None = None
        self.processed: ProcessedSpectra | None = None
        self.fits: dict[str, FitResult] = {}
        self.cluster_plot_data = None
        self.cluster_summary_data = None
        self.cluster_pick_map: dict[int, object] = {}
        self.cluster_annotation = None

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_preprocessing_tab()
        self._build_decomposition_tab()
        self._build_results_tab()
        self._build_clustering_tab()

        self.tabs.setTabEnabled(1, False)
        self.tabs.setTabEnabled(2, False)
        self.tabs.setTabEnabled(3, False)
        self.statusBar().showMessage("Select a file to start.")

    def _info_button(self, info_text: str) -> QToolButton:
        button = QToolButton()
        button.setText("?")
        button.setAutoRaise(True)
        button.setFixedSize(22, 22)
        button.setToolTip(info_text)
        button.clicked.connect(lambda: QMessageBox.information(self, "Parameter Help", info_text))
        return button

    def _field_with_info(self, label_text: str, info_text: str) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QLabel(label_text))
        row.addWidget(self._info_button(info_text))
        row.addStretch(1)
        return container

    def _control_with_info(self, control: QWidget, info_text: str) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(control)
        row.addWidget(self._info_button(info_text))
        row.addStretch(1)
        return container

    def _build_preprocessing_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        controls = QVBoxLayout()

        file_group = QGroupBox("Input")
        file_layout = QVBoxLayout(file_group)
        self.select_file_button = QPushButton("Select File")
        self.select_file_button.clicked.connect(self.on_select_file)
        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        file_button_row = QHBoxLayout()
        file_button_row.addWidget(self.select_file_button)
        file_button_row.addWidget(self._info_button("Select the input CSV file containing X in the first column and spectra in the next columns."))
        file_button_row.addStretch(1)
        file_layout.addLayout(file_button_row)
        file_layout.addWidget(self.file_label)
        controls.addWidget(file_group)

        validity_group = QGroupBox("Validity Range")
        validity_layout = QFormLayout(validity_group)
        self.x1_spin = QDoubleSpinBox()
        self.x2_spin = QDoubleSpinBox()
        for spin in (self.x1_spin, self.x2_spin):
            spin.setDecimals(6)
            spin.setEnabled(False)
        validity_layout.addRow(
            self._field_with_info("X1", "Lower bound of the valid X range. Data before X1 is excluded from processing."),
            self.x1_spin,
        )
        validity_layout.addRow(
            self._field_with_info("X2", "Upper bound of the valid X range. Data after X2 is excluded from processing."),
            self.x2_spin,
        )
        controls.addWidget(validity_group)

        filter_group = QGroupBox("Denoising")
        filter_layout = QVBoxLayout(filter_group)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("FFT Low-pass", userData="fft_lowpass")
        self.filter_combo.addItem("Savitzky-Golay", userData="savgol")
        self.filter_combo.currentIndexChanged.connect(self.on_filter_method_changed)

        self.fft_params_group = QGroupBox("FFT Parameters")
        fft_form = QFormLayout(self.fft_params_group)
        self.fft_cutoff_spin = QDoubleSpinBox()
        self.fft_cutoff_spin.setRange(0.001, 0.5)
        self.fft_cutoff_spin.setSingleStep(0.005)
        self.fft_cutoff_spin.setValue(0.08)
        fft_form.addRow(
            self._field_with_info("Cutoff ratio", "Fraction of frequency range kept in FFT filtering. Lower values remove more high-frequency noise."),
            self.fft_cutoff_spin,
        )

        self.sg_params_group = QGroupBox("Savitzky-Golay Parameters")
        sg_form = QFormLayout(self.sg_params_group)
        self.sg_window_spin = QSpinBox()
        self.sg_window_spin.setRange(3, 401)
        self.sg_window_spin.setValue(21)
        self.sg_poly_spin = QSpinBox()
        self.sg_poly_spin.setRange(1, 10)
        self.sg_poly_spin.setValue(3)
        sg_form.addRow(
            self._field_with_info("Window length", "Number of points used for Savitzky-Golay smoothing. Larger values smooth more."),
            self.sg_window_spin,
        )
        sg_form.addRow(
            self._field_with_info("Polyorder", "Polynomial degree for Savitzky-Golay smoothing. Higher values preserve more detail."),
            self.sg_poly_spin,
        )

        filter_layout.addWidget(
            self._control_with_info(
                self.filter_combo,
                "Choose denoising method: FFT low-pass removes high-frequency content; Savitzky-Golay applies polynomial smoothing.",
            )
        )
        filter_layout.addWidget(self.fft_params_group)
        filter_layout.addWidget(self.sg_params_group)
        controls.addWidget(filter_group)

        preview_group = QGroupBox("Preview and Confirm")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_spectrum_combo = QComboBox()
        self.preview_spectrum_combo.setEnabled(False)
        self.preview_button = QPushButton("Preview first spectrum")
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self.on_preview_preprocessing)

        self.confirm_button = QPushButton("Confirm preprocessing")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.on_confirm_preprocessing)

        preview_layout.addWidget(
            self._field_with_info("Reference spectrum", "Spectrum used to preview preprocessing before confirming and applying it to all spectra.")
        )
        preview_layout.addWidget(self.preview_spectrum_combo)
        preview_layout.addWidget(self.preview_button)
        preview_layout.addWidget(self.confirm_button)
        controls.addWidget(preview_group)

        controls.addStretch(1)

        self.preprocess_canvas = MplCanvas()
        self.preprocess_canvas.ax.set_title("Preprocessing preview")
        self.preprocess_canvas.ax.set_xlabel("X")
        self.preprocess_canvas.ax.set_ylabel("Intensity")

        layout.addLayout(controls, 1)
        layout.addWidget(self.preprocess_canvas, 2)

        self.tabs.addTab(tab, "1. Preprocessing")
        self.on_filter_method_changed(0)

    def _build_decomposition_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        controls = QVBoxLayout()

        setup_group = QGroupBox("Decomposition Setup")
        setup_form = QFormLayout(setup_group)
        self.decomp_spectrum_combo = QComboBox()
        self.decomp_spectrum_combo.currentIndexChanged.connect(self.on_detect_peaks)

        self.model_combo = QComboBox()
        self.model_combo.addItem("Asymmetric Gaussian", userData="asymmetric_gaussian")
        self.model_combo.addItem("Gaussian", userData="gaussian")
        self.model_combo.addItem("Lorentzian", userData="lorentzian")

        self.prominence_spin = QDoubleSpinBox()
        self.prominence_spin.setRange(0.0, 1_000_000.0)
        self.prominence_spin.setValue(5.0)
        self.prominence_spin.setDecimals(4)

        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(1.0, 10_000.0)
        self.distance_spin.setValue(10.0)

        self.hidden_peak_mode_combo = QComboBox()
        self.hidden_peak_mode_combo.addItem("Disabled", userData="disabled")
        self.hidden_peak_mode_combo.addItem("Heuristic split", userData="heuristic")
        self.hidden_peak_mode_combo.addItem("Derivative (slope + 2nd deriv)", userData="derivative")
        self.hidden_peak_mode_combo.addItem("Local AIC (1 vs 2)", userData="aic_local")
        self.hidden_peak_mode_combo.setCurrentIndex(2)

        self.split_factor_spin = QDoubleSpinBox()
        self.split_factor_spin.setRange(1.1, 4.0)
        self.split_factor_spin.setSingleStep(0.1)
        self.split_factor_spin.setValue(1.6)
        self.split_factor_spin.setDecimals(2)

        self.max_skew_spin = QDoubleSpinBox()
        self.max_skew_spin.setRange(0.0, 1.0)
        self.max_skew_spin.setSingleStep(0.05)
        self.max_skew_spin.setValue(0.35)
        self.max_skew_spin.setDecimals(2)

        setup_form.addRow(
            self._field_with_info("Spectrum", "Select which processed spectrum to detect and fit peaks on."),
            self.decomp_spectrum_combo,
        )
        setup_form.addRow(
            self._field_with_info("Peak model", "Model used for each fitted peak component."),
            self.model_combo,
        )
        setup_form.addRow(
            self._field_with_info("Prominence", "Minimum prominence for peak detection. Increase to ignore smaller peaks/noise."),
            self.prominence_spin,
        )
        setup_form.addRow(
            self._field_with_info("Distance", "Minimum spacing between detected peaks in sample points."),
            self.distance_spin,
        )
        setup_form.addRow(
            self._field_with_info("Hidden peak mode", "How broad peaks are expanded into possible hidden components before fitting."),
            self.hidden_peak_mode_combo,
        )
        setup_form.addRow(
            self._field_with_info("Split / window factor", "Controls split aggressiveness or local analysis window size, depending on mode."),
            self.split_factor_spin,
        )
        setup_form.addRow(
            self._field_with_info("Max skew (0 = Gaussian)", "Maximum asymmetry for asymmetric Gaussian. Set 0 to force classic Gaussian behavior."),
            self.max_skew_spin,
        )
        controls.addWidget(setup_group)

        button_row = QHBoxLayout()
        self.detect_button = QPushButton("Detect Peaks")
        self.detect_button.clicked.connect(self.on_detect_peaks)
        self.fit_selected_button = QPushButton("Fit this spectrum")
        self.fit_selected_button.clicked.connect(self.on_fit_selected)
        self.fit_all_button = QPushButton("Fit ALL spectra")
        self.fit_all_button.clicked.connect(self.on_fit_all)
        button_row.addWidget(self.detect_button)
        button_row.addWidget(self.fit_selected_button)
        button_row.addWidget(self.fit_all_button)
        controls.addLayout(button_row)

        self.peak_table = QTableWidget(0, 3)
        self.peak_table.setHorizontalHeaderLabels(["Center", "Amplitude", "Width"])
        controls.addWidget(self.peak_table)

        table_buttons = QHBoxLayout()
        self.add_peak_button = QPushButton("Add row")
        self.add_peak_button.clicked.connect(self.on_add_peak_row)
        self.remove_peak_button = QPushButton("Remove row")
        self.remove_peak_button.clicked.connect(self.on_remove_peak_row)
        table_buttons.addWidget(self.add_peak_button)
        table_buttons.addWidget(self.remove_peak_button)
        controls.addLayout(table_buttons)

        controls.addStretch(1)

        self.decomp_canvas = MplCanvas()
        self.decomp_canvas.ax.set_title("Decomposition")
        self.decomp_canvas.ax.set_xlabel("X")
        self.decomp_canvas.ax.set_ylabel("Intensity")

        layout.addLayout(controls, 1)
        layout.addWidget(self.decomp_canvas, 2)

        self.tabs.addTab(tab, "2. Decomposition")

    def _build_results_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        controls = QVBoxLayout()

        view_group = QGroupBox("Final Results View")
        view_form = QFormLayout(view_group)
        self.results_spectrum_combo = QComboBox()
        self.results_spectrum_combo.currentIndexChanged.connect(self.on_update_results_plot)

        self.show_raw_cb = QCheckBox("Show Raw")
        self.show_raw_cb.setChecked(True)
        self.show_filtered_cb = QCheckBox("Show Filtered")
        self.show_filtered_cb.setChecked(True)
        self.show_fit_cb = QCheckBox("Show Decomposed Sum")
        self.show_fit_cb.setChecked(True)
        self.show_components_cb = QCheckBox("Show Individual Peaks")
        self.show_components_cb.setChecked(True)

        for cb in (self.show_raw_cb, self.show_filtered_cb, self.show_fit_cb, self.show_components_cb):
            cb.stateChanged.connect(self.on_update_results_plot)

        view_form.addRow(
            self._field_with_info("Spectrum", "Choose which spectrum is displayed in the final results chart."),
            self.results_spectrum_combo,
        )
        view_form.addRow(self._control_with_info(self.show_raw_cb, "Show original unfiltered signal."))
        view_form.addRow(self._control_with_info(self.show_filtered_cb, "Show filtered signal used for fitting."))
        view_form.addRow(self._control_with_info(self.show_fit_cb, "Show reconstructed sum of all fitted peaks."))
        view_form.addRow(self._control_with_info(self.show_components_cb, "Show each fitted peak component separately."))
        controls.addWidget(view_group)

        self.refresh_results_button = QPushButton("Refresh visualization")
        self.refresh_results_button.clicked.connect(self.on_update_results_plot)
        self.export_button = QPushButton("Export all results to CSV")
        self.export_button.clicked.connect(self.on_export_results)
        controls.addWidget(self.refresh_results_button)
        controls.addWidget(self.export_button)
        controls.addStretch(1)

        self.results_canvas = MplCanvas()
        self.results_canvas.ax.set_title("Final Results")
        self.results_canvas.ax.set_xlabel("X")
        self.results_canvas.ax.set_ylabel("Intensity")

        layout.addLayout(controls, 1)
        layout.addWidget(self.results_canvas, 2)

        self.tabs.addTab(tab, "3. Final Results")

    def _build_clustering_tab(self) -> None:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        controls = QVBoxLayout()

        view_group = QGroupBox("Peak Clustering View")
        view_layout = QVBoxLayout(view_group)
        view_layout.addWidget(
            self._field_with_info(
                "Spectra",
                "Select one or more fitted spectra to compare their peak centers and relative intensities in a single graph.",
            )
        )

        self.cluster_spectra_list = QListWidget()
        self.cluster_spectra_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.cluster_spectra_list.itemSelectionChanged.connect(self.on_update_clustering_plot)
        view_layout.addWidget(self.cluster_spectra_list)

        view_form = QFormLayout()
        self.cluster_mode_combo = QComboBox()
        self.cluster_mode_combo.addItem("Scatter only", userData="scatter")
        self.cluster_mode_combo.addItem("Auto-group peaks", userData="clustered")
        self.cluster_mode_combo.currentIndexChanged.connect(self.on_update_clustering_plot)

        self.cluster_tolerance_spin = QDoubleSpinBox()
        self.cluster_tolerance_spin.setRange(0.0001, 10_000.0)
        self.cluster_tolerance_spin.setDecimals(4)
        self.cluster_tolerance_spin.setValue(10.0)
        self.cluster_tolerance_spin.valueChanged.connect(self.on_update_clustering_plot)

        self.cluster_min_relative_spin = QDoubleSpinBox()
        self.cluster_min_relative_spin.setRange(0.0, 1.0)
        self.cluster_min_relative_spin.setDecimals(4)
        self.cluster_min_relative_spin.setSingleStep(0.01)
        self.cluster_min_relative_spin.setValue(0.0)
        self.cluster_min_relative_spin.valueChanged.connect(self.on_update_clustering_plot)

        view_form.addRow(
            self._field_with_info("Display mode", "Choose whether to overlay all fitted peaks directly or group nearby center positions into peak clusters."),
            self.cluster_mode_combo,
        )
        view_form.addRow(
            self._field_with_info("Grouping tolerance", "Maximum distance in center position used to merge peaks into the same cluster when auto-grouping is enabled."),
            self.cluster_tolerance_spin,
        )
        view_form.addRow(
            self._field_with_info("Min relative intensity", "Ignore all peaks whose relative intensity is below this user-defined threshold (0 to 1)."),
            self.cluster_min_relative_spin,
        )
        view_layout.addLayout(view_form)
        controls.addWidget(view_group)

        list_buttons = QHBoxLayout()
        self.cluster_select_all_button = QPushButton("Select all")
        self.cluster_select_all_button.clicked.connect(self.on_select_all_clustering_spectra)
        self.cluster_clear_button = QPushButton("Clear selection")
        self.cluster_clear_button.clicked.connect(self.on_clear_clustering_selection)
        list_buttons.addWidget(self.cluster_select_all_button)
        list_buttons.addWidget(self.cluster_clear_button)
        controls.addLayout(list_buttons)

        self.cluster_refresh_button = QPushButton("Refresh clustering plot")
        self.cluster_refresh_button.clicked.connect(self.on_update_clustering_plot)
        controls.addWidget(self.cluster_refresh_button)

        export_buttons = QHBoxLayout()
        self.cluster_export_image_button = QPushButton("Save image")
        self.cluster_export_image_button.clicked.connect(self.on_save_clustering_image)
        self.cluster_export_data_button = QPushButton("Export raw data")
        self.cluster_export_data_button.clicked.connect(self.on_export_clustering_data)
        export_buttons.addWidget(self.cluster_export_image_button)
        export_buttons.addWidget(self.cluster_export_data_button)
        controls.addLayout(export_buttons)

        self.cluster_point_label = QLabel("Click a point in the graph to see the spectrum name and peak details.")
        self.cluster_point_label.setWordWrap(True)
        controls.addWidget(self.cluster_point_label)
        controls.addStretch(1)

        self.cluster_canvas = MplCanvas()
        self.cluster_canvas.ax.set_title("Peak clustering")
        self.cluster_canvas.ax.set_xlabel("Center position")
        self.cluster_canvas.ax.set_ylabel("Relative intensity")
        self.cluster_canvas.mpl_connect("pick_event", self.on_clustering_point_picked)

        layout.addLayout(controls, 1)
        layout.addWidget(self.cluster_canvas, 2)

        self.tabs.addTab(tab, "4. Peak Clustering")
        self._show_empty_clustering_message("Fit one or more spectra to populate the peak clustering view.")

    def on_filter_method_changed(self, _: int) -> None:
        method = self.filter_combo.currentData()
        self.fft_params_group.setVisible(method == "fft_lowpass")
        self.sg_params_group.setVisible(method == "savgol")

    def _current_filter_setup(self) -> Tuple[str, dict[str, float]]:
        method = self.filter_combo.currentData()
        if method == "fft_lowpass":
            return method, {"cutoff_ratio": float(self.fft_cutoff_spin.value())}
        return method, {
            "window_length": float(self.sg_window_spin.value()),
            "polyorder": float(self.sg_poly_spin.value()),
        }

    def _populate_spectrum_selectors(self, names: List[str]) -> None:
        for combo in (self.preview_spectrum_combo, self.decomp_spectrum_combo, self.results_spectrum_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.blockSignals(False)

        self._sync_clustering_spectrum_list(names)
        self.preview_spectrum_combo.setEnabled(True)

    def _sync_clustering_spectrum_list(self, names: List[str]) -> None:
        self.cluster_spectra_list.blockSignals(True)
        self.cluster_spectra_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            self.cluster_spectra_list.addItem(item)
            item.setSelected(True)
        self.cluster_spectra_list.blockSignals(False)

    def _selected_clustering_spectra(self) -> List[str]:
        return [item.text() for item in self.cluster_spectra_list.selectedItems()]

    def on_select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select spectra file",
            "",
            "CSV files (*.csv);;All files (*.*)",
        )
        if not file_path:
            return

        try:
            self.dataset = load_spectra_csv(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", str(exc))
            return

        self.file_label.setText(file_path)
        x_min = float(np.min(self.dataset.x))
        x_max = float(np.max(self.dataset.x))

        self.x1_spin.setEnabled(True)
        self.x2_spin.setEnabled(True)
        self.x1_spin.setRange(x_min, x_max)
        self.x2_spin.setRange(x_min, x_max)
        self.x1_spin.setValue(x_min)
        self.x2_spin.setValue(x_max)

        self.preview_button.setEnabled(True)
        self.confirm_button.setEnabled(True)

        self._populate_spectrum_selectors(self.dataset.spectrum_names)

        self.processed = None
        self.fits = {}
        self.tabs.setTabEnabled(1, False)
        self.tabs.setTabEnabled(2, False)
        self.tabs.setTabEnabled(3, False)
        self.on_update_clustering_plot()

        self.statusBar().showMessage("File loaded. Set X1/X2 and preview preprocessing.")

    def on_preview_preprocessing(self) -> None:
        if self.dataset is None:
            return

        try:
            method, params = self._current_filter_setup()
            preview = apply_validity_and_filter(
                self.dataset,
                x1=float(self.x1_spin.value()),
                x2=float(self.x2_spin.value()),
                filter_method=method,
                filter_params=params,
            )
            spectrum_name = self.preview_spectrum_combo.currentText() or self.dataset.spectrum_names[0]
            x = preview.x
            y_raw = preview.raw[spectrum_name]
            y_filtered = preview.filtered[spectrum_name]
        except Exception as exc:
            QMessageBox.warning(self, "Preview error", str(exc))
            return

        self.preprocess_canvas.ax.clear()
        self.preprocess_canvas.ax.plot(x, y_raw, color="gray", linewidth=1.0, label="Raw")
        self.preprocess_canvas.ax.plot(x, y_filtered, color="tab:blue", linewidth=1.5, label="Filtered")
        self.preprocess_canvas.ax.set_title(f"Preview - {spectrum_name}")
        self.preprocess_canvas.ax.set_xlabel(self.dataset.x_name)
        self.preprocess_canvas.ax.set_ylabel("Intensity")
        self.preprocess_canvas.ax.legend(loc="best")
        self.preprocess_canvas.draw()

        self.statusBar().showMessage("Preview updated.")

    def on_confirm_preprocessing(self) -> None:
        if self.dataset is None:
            return

        try:
            method, params = self._current_filter_setup()
            self.processed = apply_validity_and_filter(
                self.dataset,
                x1=float(self.x1_spin.value()),
                x2=float(self.x2_spin.value()),
                filter_method=method,
                filter_params=params,
            )
            self.fits = {}
            self.tabs.setTabEnabled(1, True)
            self.tabs.setTabEnabled(2, False)
            self.tabs.setTabEnabled(3, False)
            self.tabs.setCurrentIndex(1)
            self.statusBar().showMessage("Preprocessing confirmed. Decomposition unlocked.")
            self.on_detect_peaks()
            self.on_update_clustering_plot()
        except Exception as exc:
            QMessageBox.warning(self, "Preprocessing error", str(exc))

    def _current_spectrum_for_decomp(self) -> str | None:
        name = self.decomp_spectrum_combo.currentText()
        return name if name else None

    def _set_peak_table(self, peaks: List[Tuple[float, float, float]]) -> None:
        self.peak_table.setRowCount(0)
        for center, amplitude, width in peaks:
            row = self.peak_table.rowCount()
            self.peak_table.insertRow(row)
            self.peak_table.setItem(row, 0, QTableWidgetItem(f"{center:.6g}"))
            self.peak_table.setItem(row, 1, QTableWidgetItem(f"{amplitude:.6g}"))
            self.peak_table.setItem(row, 2, QTableWidgetItem(f"{width:.6g}"))

    def _read_peaks_from_table(self) -> List[Tuple[float, float, float]]:
        peaks: List[Tuple[float, float, float]] = []
        for row in range(self.peak_table.rowCount()):
            center_item = self.peak_table.item(row, 0)
            amp_item = self.peak_table.item(row, 1)
            width_item = self.peak_table.item(row, 2)
            if not center_item or not amp_item or not width_item:
                continue
            center = float(center_item.text())
            amp = max(float(amp_item.text()), 1e-9)
            width = max(float(width_item.text()), 1e-9)
            peaks.append((center, amp, width))
        return peaks

    def on_detect_peaks(self) -> None:
        if self.processed is None:
            return

        spectrum_name = self._current_spectrum_for_decomp()
        if not spectrum_name:
            return

        x = self.processed.x
        y = self.processed.filtered[spectrum_name]
        prominence = float(self.prominence_spin.value())
        distance = float(self.distance_spin.value())

        peaks = detect_initial_peaks(x, y, prominence=prominence, distance=distance)
        self._set_peak_table(peaks)

        self.decomp_canvas.ax.clear()
        self.decomp_canvas.ax.plot(x, y, color="tab:blue", linewidth=1.5, label="Filtered")
        self.decomp_canvas.ax.scatter(
            [p[0] for p in peaks],
            [p[1] for p in peaks],
            color="tab:red",
            s=30,
            label="Detected peaks",
        )
        self.decomp_canvas.ax.set_title(f"Detected peaks - {spectrum_name}")
        self.decomp_canvas.ax.set_xlabel(self.dataset.x_name if self.dataset else "X")
        self.decomp_canvas.ax.set_ylabel("Intensity")
        self.decomp_canvas.ax.legend(loc="best")
        self.decomp_canvas.draw()

    def on_add_peak_row(self) -> None:
        row = self.peak_table.rowCount()
        self.peak_table.insertRow(row)
        for col in range(3):
            self.peak_table.setItem(row, col, QTableWidgetItem("0.0"))

    def on_remove_peak_row(self) -> None:
        rows = sorted({idx.row() for idx in self.peak_table.selectedIndexes()}, reverse=True)
        if not rows and self.peak_table.rowCount() > 0:
            rows = [self.peak_table.rowCount() - 1]
        for row in rows:
            self.peak_table.removeRow(row)

    def on_fit_selected(self) -> None:
        if self.processed is None:
            return

        spectrum_name = self._current_spectrum_for_decomp()
        if not spectrum_name:
            return

        progress = QProgressDialog("Fitting selected spectrum...", "Cancel", 0, 5, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        progress.setLabelText("Reading peak initialization...")
        peaks = self._read_peaks_from_table()
        progress.setValue(1)
        QApplication.processEvents()
        if progress.wasCanceled():
            progress.close()
            self.statusBar().showMessage("Fit canceled.")
            return

        if not peaks:
            self.on_detect_peaks()
            peaks = self._read_peaks_from_table()
            if not peaks:
                progress.close()
                QMessageBox.warning(self, "Fit error", "No peaks available for fitting.")
                return

        model = self.model_combo.currentData()
        x = self.processed.x
        y = self.processed.filtered[spectrum_name]
        skew_limit = float(self.max_skew_spin.value())

        progress.setLabelText("Refining hidden peaks...")
        hidden_mode = self.hidden_peak_mode_combo.currentData()
        if hidden_mode == "heuristic":
            peaks = expand_peaks_for_hidden_doublets(
                peaks,
                x_min=float(np.min(x)),
                x_max=float(np.max(x)),
                split_factor=float(self.split_factor_spin.value()),
                max_subpeaks_per_peak=2,
            )
            self._set_peak_table(peaks)
        elif hidden_mode == "derivative":
            peaks = expand_peaks_with_derivative_mode(
                x,
                y,
                peaks,
                window_factor=float(self.split_factor_spin.value()),
            )
            self._set_peak_table(peaks)
        elif hidden_mode == "aic_local":
            peaks = expand_peaks_with_local_aic(
                x,
                y,
                peaks,
                model=model,
                window_factor=float(self.split_factor_spin.value()),
                asymmetry_limit=skew_limit,
            )
            self._set_peak_table(peaks)
        progress.setValue(2)
        QApplication.processEvents()
        if progress.wasCanceled():
            progress.close()
            self.statusBar().showMessage("Fit canceled.")
            return

        try:
            progress.setLabelText("Running curve fitting...")
            progress.setValue(3)
            QApplication.processEvents()
            if progress.wasCanceled():
                progress.close()
                self.statusBar().showMessage("Fit canceled.")
                return
            fit = fit_spectrum(x, y, initial_peaks=peaks, model=model, asymmetry_limit=skew_limit)
        except Exception as exc:
            progress.close()
            QMessageBox.warning(self, "Fit error", str(exc))
            return

        self.fits[spectrum_name] = fit
        self.tabs.setTabEnabled(2, True)
        self.tabs.setTabEnabled(3, True)

        progress.setLabelText("Rendering results...")
        progress.setValue(4)
        QApplication.processEvents()
        if progress.wasCanceled():
            progress.close()
            self.statusBar().showMessage("Fit canceled.")
            return

        self.decomp_canvas.ax.clear()
        self.decomp_canvas.ax.plot(x, y, color="tab:blue", linewidth=1.2, label="Filtered")
        self.decomp_canvas.ax.plot(x, fit.fitted_sum, color="tab:red", linestyle="--", linewidth=1.6, label="Fit sum")
        for i in range(fit.components.shape[0]):
            self.decomp_canvas.ax.plot(x, fit.components[i], linewidth=1.0, alpha=0.8, label=f"Peak {i + 1}")

        self.decomp_canvas.ax.set_title(f"Decomposition - {spectrum_name}")
        self.decomp_canvas.ax.set_xlabel(self.dataset.x_name if self.dataset else "X")
        self.decomp_canvas.ax.set_ylabel("Intensity")
        self.decomp_canvas.ax.legend(loc="best", fontsize=8)
        self.decomp_canvas.draw()

        self.statusBar().showMessage(f"Fitted spectrum: {spectrum_name}")
        self.on_update_results_plot()
        self.on_update_clustering_plot()

        progress.setValue(5)
        progress.close()

    def on_fit_all(self) -> None:
        if self.processed is None or self.dataset is None:
            return

        model = self.model_combo.currentData()
        prominence = float(self.prominence_spin.value())
        distance = float(self.distance_spin.value())
        hidden_mode = self.hidden_peak_mode_combo.currentData()
        skew_limit = float(self.max_skew_spin.value())

        progress = QProgressDialog("Fitting all spectra...", "Cancel", 0, len(self.dataset.spectrum_names), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        fit_count = 0
        error_count = 0
        errors: List[str] = []

        for idx, name in enumerate(self.dataset.spectrum_names, start=1):
            if progress.wasCanceled():
                break

            try:
                y = self.processed.filtered[name]
                initial = detect_initial_peaks(self.processed.x, y, prominence=prominence, distance=distance)
                if hidden_mode == "heuristic":
                    initial = expand_peaks_for_hidden_doublets(
                        initial,
                        x_min=float(np.min(self.processed.x)),
                        x_max=float(np.max(self.processed.x)),
                        split_factor=float(self.split_factor_spin.value()),
                        max_subpeaks_per_peak=2,
                    )
                elif hidden_mode == "derivative":
                    initial = expand_peaks_with_derivative_mode(
                        self.processed.x,
                        y,
                        initial,
                        window_factor=float(self.split_factor_spin.value()),
                    )
                elif hidden_mode == "aic_local":
                    initial = expand_peaks_with_local_aic(
                        self.processed.x,
                        y,
                        initial,
                        model=model,
                        window_factor=float(self.split_factor_spin.value()),
                        asymmetry_limit=skew_limit,
                    )
                self.fits[name] = fit_spectrum(
                    self.processed.x,
                    y,
                    initial_peaks=initial,
                    model=model,
                    asymmetry_limit=skew_limit,
                )
                fit_count += 1
            except Exception as exc:
                error_count += 1
                errors.append(f"{name}: {exc}")

            progress.setValue(idx)
            QApplication.processEvents()

        progress.close()

        if fit_count > 0:
            self.tabs.setTabEnabled(2, True)
            self.tabs.setTabEnabled(3, True)
            self.on_update_results_plot()
            self.on_update_clustering_plot()

        msg = f"Fit complete. Success: {fit_count}"
        if error_count:
            msg += f", Errors: {error_count}"
        self.statusBar().showMessage(msg)

        if error_count:
            preview = "\n".join(errors[:8])
            QMessageBox.warning(self, "Some fits failed", f"{msg}\n\n{preview}")
        else:
            QMessageBox.information(self, "Fit completed", msg)

    def on_update_results_plot(self) -> None:
        if self.processed is None:
            return

        spectrum_name = self.results_spectrum_combo.currentText()
        if not spectrum_name:
            return

        x = self.processed.x
        y_raw = self.processed.raw[spectrum_name]
        y_filtered = self.processed.filtered[spectrum_name]
        fit = self.fits.get(spectrum_name)

        self.results_canvas.ax.clear()

        if self.show_raw_cb.isChecked():
            self.results_canvas.ax.plot(x, y_raw, color="gray", linewidth=1.0, label="Raw")
        if self.show_filtered_cb.isChecked():
            self.results_canvas.ax.plot(x, y_filtered, color="tab:blue", linewidth=1.2, label="Filtered")
        if fit is not None and self.show_fit_cb.isChecked():
            self.results_canvas.ax.plot(x, fit.fitted_sum, color="tab:red", linestyle="--", linewidth=1.5, label="Decomposed sum")
        if fit is not None and self.show_components_cb.isChecked():
            for i in range(fit.components.shape[0]):
                self.results_canvas.ax.plot(x, fit.components[i], linewidth=1.0, alpha=0.8, label=f"Peak {i + 1}")

        self.results_canvas.ax.set_title(f"Final results - {spectrum_name}")
        self.results_canvas.ax.set_xlabel(self.dataset.x_name if self.dataset else "X")
        self.results_canvas.ax.set_ylabel("Intensity")
        self.results_canvas.ax.legend(loc="best", fontsize=8)
        self.results_canvas.draw()

    def _show_empty_clustering_message(self, message: str) -> None:
        self.cluster_plot_data = None
        self.cluster_summary_data = None
        self.cluster_pick_map = {}
        if self.cluster_annotation is not None:
            try:
                self.cluster_annotation.remove()
            except Exception:
                pass
            self.cluster_annotation = None

        self.cluster_canvas.ax.clear()
        self.cluster_canvas.ax.set_title("Peak clustering")
        self.cluster_canvas.ax.set_xlabel("Center position")
        self.cluster_canvas.ax.set_ylabel("Relative intensity")
        self.cluster_canvas.ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            wrap=True,
            transform=self.cluster_canvas.ax.transAxes,
        )
        self.cluster_point_label.setText("Click a point in the graph to see the spectrum name and peak details.")
        self.cluster_canvas.draw()

    def on_select_all_clustering_spectra(self) -> None:
        self.cluster_spectra_list.blockSignals(True)
        for row in range(self.cluster_spectra_list.count()):
            item = self.cluster_spectra_list.item(row)
            if item is not None:
                item.setSelected(True)
        self.cluster_spectra_list.blockSignals(False)
        self.on_update_clustering_plot()

    def on_clear_clustering_selection(self) -> None:
        self.cluster_spectra_list.clearSelection()
        self.on_update_clustering_plot()

    def on_save_clustering_image(self) -> None:
        default_dir = os.path.dirname(self.dataset.file_path) if self.dataset is not None else ""
        default_path = os.path.join(default_dir, "peak_clustering.png") if default_dir else "peak_clustering.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save clustering image",
            default_path,
            "PNG Image (*.png);;PDF File (*.pdf);;SVG File (*.svg)",
        )
        if not file_path:
            return

        try:
            self.cluster_canvas.figure.savefig(file_path, dpi=300, bbox_inches="tight")
        except Exception as exc:
            QMessageBox.warning(self, "Save image error", str(exc))
            return

        self.statusBar().showMessage(f"Clustering image saved: {file_path}")

    def on_export_clustering_data(self) -> None:
        if self.cluster_plot_data is None or len(self.cluster_plot_data) == 0:
            self.on_update_clustering_plot()

        if self.cluster_plot_data is None or len(self.cluster_plot_data) == 0:
            QMessageBox.warning(self, "Export error", "No clustering data is currently available to export.")
            return

        default_dir = os.path.dirname(self.dataset.file_path) if self.dataset is not None else ""
        default_path = os.path.join(default_dir, "peak_clustering_data.csv") if default_dir else "peak_clustering_data.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export clustering data",
            default_path,
            "CSV files (*.csv);;All files (*.*)",
        )
        if not file_path:
            return

        try:
            export_df = self.cluster_plot_data.copy()
            preferred_order = [
                "Point_ID",
                "Spectrum",
                "Peak_N",
                "Model",
                "Center",
                "Amplitude",
                "Relative_Intensity",
                "Area",
                "Width",
                "Width_Left",
                "Width_Right",
                "Skew",
                "Cluster_ID",
                "Cluster_Label",
                "Cluster_Position",
                "Cluster_Population",
                "Cluster_Width",
            ]
            ordered_cols = [col for col in preferred_order if col in export_df.columns]
            remaining_cols = [col for col in export_df.columns if col not in ordered_cols]
            export_df = export_df.loc[:, ordered_cols + remaining_cols]

            numeric_cols = export_df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                export_df.loc[:, numeric_cols] = export_df.loc[:, numeric_cols].mask(export_df.loc[:, numeric_cols].abs() < 1e-12, 0.0)
            export_df.to_csv(file_path, index=False)

            summary_path = None
            if self.cluster_summary_data is not None and len(self.cluster_summary_data) > 0:
                summary_path = os.path.splitext(file_path)[0] + "_cluster_summary.csv"
                self.cluster_summary_data.to_csv(summary_path, index=False)
        except Exception as exc:
            QMessageBox.warning(self, "Export error", str(exc))
            return

        msg = f"Clustering raw data exported: {file_path}"
        if summary_path is not None:
            msg += f" | Cluster summary: {summary_path}"
        self.statusBar().showMessage(msg)

    def on_clustering_point_picked(self, event) -> None:
        point_df = self.cluster_pick_map.get(id(event.artist))
        if point_df is None or len(getattr(event, "ind", [])) == 0:
            return

        row = point_df.iloc[int(event.ind[0])]
        center = float(row["Center"])
        rel_intensity = float(row["Relative_Intensity"])
        spectrum_name = str(row["Spectrum"])
        peak_n = int(row["Peak_N"])
        point_id = int(row["Point_ID"]) if "Point_ID" in row.index else peak_n

        cluster_text = ""
        cluster_label = ""
        if "Cluster_ID" in row.index:
            cluster_id = int(row["Cluster_ID"])
            cluster_position = float(row.get("Cluster_Position", center))
            cluster_population = int(row.get("Cluster_Population", 1))
            cluster_width = float(row.get("Cluster_Width", row.get("Width", 0.0)))
            cluster_label = f" | Cluster {cluster_id}"
            cluster_text = (
                f"\nPoint ID: {point_id}"
                f"\nCluster ID: {cluster_id}"
                f"\nCluster position: {cluster_position:.6g}"
                f"\nCluster population: {cluster_population}"
                f"\nCluster width: {cluster_width:.6g}"
            )

        if self.cluster_annotation is not None:
            try:
                self.cluster_annotation.remove()
            except Exception:
                pass

        self.cluster_annotation = self.cluster_canvas.ax.annotate(
            f"Spectrum: {spectrum_name}\nPeak: {peak_n}\nCenter: {center:.6g}\nRelative intensity: {rel_intensity:.4f}{cluster_text}",
            xy=(center, rel_intensity),
            xytext=(12, 12),
            textcoords="offset points",
            bbox={"boxstyle": "round", "fc": "white", "ec": "0.5", "alpha": 0.95},
            arrowprops={"arrowstyle": "->", "color": "0.35"},
        )
        self.cluster_point_label.setText(
            f"Selected spectrum: {spectrum_name} | Point ID {point_id} | Peak {peak_n}{cluster_label} | Center {center:.6g} | Relative intensity {rel_intensity:.4f}"
        )
        self.cluster_canvas.draw_idle()
        self.statusBar().showMessage(f"Selected point from spectrum: {spectrum_name}")

    def _cluster_ids_from_centers(self, centers: np.ndarray, tolerance: float) -> np.ndarray:
        if centers.size == 0:
            return np.array([], dtype=int)

        tolerance = max(float(tolerance), 1e-9)
        order = np.argsort(centers)
        cluster_ids = np.zeros(centers.size, dtype=int)
        current_cluster = 0
        cluster_sum = 0.0
        cluster_size = 0

        for idx in order:
            center = float(centers[idx])
            if cluster_size == 0:
                current_cluster = 1
                cluster_sum = center
                cluster_size = 1
                cluster_ids[idx] = current_cluster
                continue

            cluster_mean = cluster_sum / cluster_size
            if abs(center - cluster_mean) <= tolerance:
                cluster_sum += center
                cluster_size += 1
            else:
                current_cluster += 1
                cluster_sum = center
                cluster_size = 1
            cluster_ids[idx] = current_cluster

        return cluster_ids

    def _attach_cluster_metadata(self, summary):
        summary = summary.copy().reset_index(drop=True)
        summary["Point_ID"] = np.arange(1, len(summary) + 1, dtype=int)
        summary["Cluster_ID"] = self._cluster_ids_from_centers(
            summary["Center"].to_numpy(dtype=float),
            float(self.cluster_tolerance_spin.value()),
        )

        cluster_summary = (
            summary.groupby("Cluster_ID", sort=True)
            .agg(
                Cluster_Position=("Center", "mean"),
                Cluster_Population=("Center", "size"),
                Cluster_Width=("Width", "mean"),
            )
            .reset_index()
        )
        cluster_summary["Cluster_Label"] = cluster_summary["Cluster_ID"].map(lambda cid: f"Cluster {int(cid)}")

        summary = summary.merge(cluster_summary, on="Cluster_ID", how="left")
        return summary, cluster_summary

    def on_update_clustering_plot(self) -> None:
        if self.processed is None or not self.fits:
            self._show_empty_clustering_message("Fit one or more spectra to populate the peak clustering view.")
            return

        selected_spectra = self._selected_clustering_spectra()
        if not selected_spectra:
            self._show_empty_clustering_message("Select one or more spectra to compare their fitted peaks.")
            return

        summary = peaks_summary_dataframe(self.fits)
        if summary.empty:
            self._show_empty_clustering_message("No fitted peaks are available for the selected spectra.")
            return

        summary = summary[summary["Spectrum"].isin(selected_spectra)].copy()
        if summary.empty:
            self._show_empty_clustering_message("The selected spectra have not been fitted yet.")
            return

        relative_intensities = []
        for spectrum_name, amplitude in zip(summary["Spectrum"], summary["Amplitude"]):
            spectrum_max = max(float(np.max(np.abs(self.processed.filtered[str(spectrum_name)]))), 1e-12)
            relative_intensities.append(float(np.clip(float(amplitude) / spectrum_max, 0.0, 1.0)))
        summary["Relative_Intensity"] = relative_intensities

        min_relative_intensity = float(self.cluster_min_relative_spin.value())
        summary = summary[summary["Relative_Intensity"] >= min_relative_intensity].copy()
        if summary.empty:
            self._show_empty_clustering_message(
                f"No peaks remain after applying the relative-intensity threshold ({min_relative_intensity:.4f})."
            )
            return

        mode = self.cluster_mode_combo.currentData()
        self.cluster_tolerance_spin.setEnabled(mode == "clustered")

        if self.cluster_annotation is not None:
            try:
                self.cluster_annotation.remove()
            except Exception:
                pass
            self.cluster_annotation = None

        self.cluster_plot_data = None
        self.cluster_summary_data = None
        self.cluster_pick_map = {}
        self.cluster_point_label.setText("Click a point in the graph to see the spectrum name and peak details.")

        summary, cluster_summary = self._attach_cluster_metadata(summary)

        ax = self.cluster_canvas.ax
        ax.clear()

        if mode == "clustered":
            for cluster_id, cluster_df in summary.groupby("Cluster_ID", sort=True):
                cluster_position = float(cluster_df["Cluster_Position"].iloc[0])
                cluster_population = int(cluster_df["Cluster_Population"].iloc[0])
                scatter = ax.scatter(
                    cluster_df["Center"],
                    cluster_df["Relative_Intensity"],
                    s=60,
                    alpha=0.85,
                    label=f"Cluster {cluster_id} (pos {cluster_position:.3g}, n={cluster_population})",
                    picker=True,
                )
                self.cluster_pick_map[id(scatter)] = cluster_df.reset_index(drop=True)
                ax.axvline(cluster_position, color="0.85", linestyle=":", linewidth=0.8)
            title = f"Peak clustering across {summary['Spectrum'].nunique()} spectra"
        else:
            for spectrum_name, spectrum_df in summary.groupby("Spectrum", sort=False):
                scatter = ax.scatter(
                    spectrum_df["Center"],
                    spectrum_df["Relative_Intensity"],
                    s=60,
                    alpha=0.85,
                    label=str(spectrum_name),
                    picker=True,
                )
                self.cluster_pick_map[id(scatter)] = spectrum_df.reset_index(drop=True)
            title = f"Peak positions across {summary['Spectrum'].nunique()} spectra"

        self.cluster_plot_data = summary.reset_index(drop=True)
        self.cluster_summary_data = cluster_summary.reset_index(drop=True)

        ax.set_title(title)
        ax.set_xlabel("Center position")
        ax.set_ylabel("Relative intensity")
        ax.set_ylim(0.0, 1.05)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", fontsize=8)
        self.cluster_canvas.draw()

        self.statusBar().showMessage(
            f"Clustering view updated: {len(summary)} peaks from {summary['Spectrum'].nunique()} spectra with relative intensity >= {min_relative_intensity:.4f}."
        )
    def on_export_results(self) -> None:
        if self.dataset is None or self.processed is None:
            QMessageBox.warning(self, "Export error", "Load and preprocess data before exporting.")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Select output folder", os.path.dirname(self.dataset.file_path))
        if not out_dir:
            return

        written_files = 0
        tiny_threshold = 1e-3
        for name in self.dataset.spectrum_names:
            df = spectrum_result_dataframe(
                self.processed.x,
                self.processed.raw[name],
                self.processed.filtered[name],
                self.fits.get(name),
                x_name=self.dataset.x_name,
            )
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                df.loc[:, numeric_cols] = df.loc[:, numeric_cols].mask(df.loc[:, numeric_cols].abs() < tiny_threshold, 0.0)
            out_path = os.path.join(out_dir, f"{name}_results.csv")
            df.to_csv(out_path, index=False)
            written_files += 1

        summary = peaks_summary_dataframe(self.fits)
        if not summary.empty:
            numeric_cols = summary.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                summary.loc[:, numeric_cols] = summary.loc[:, numeric_cols].mask(summary.loc[:, numeric_cols].abs() < tiny_threshold, 0.0)
            summary_path = os.path.join(out_dir, "peaks_summary.csv")
            summary.to_csv(summary_path, index=False)
            written_files += 1

        QMessageBox.information(self, "Export completed", f"Export completed. Files written: {written_files}")
        self.statusBar().showMessage(f"Exported {written_files} CSV files.")
