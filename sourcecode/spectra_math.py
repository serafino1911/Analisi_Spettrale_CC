from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, peak_widths, savgol_filter

FilterMethod = Literal["fft_lowpass", "savgol"]
PeakModel = Literal["asymmetric_gaussian", "gaussian", "lorentzian"]

ASYMMETRIC_MAX_SKEW = 0.35


def _effective_model(model: PeakModel, asymmetry_limit: float) -> PeakModel:
    if model == "asymmetric_gaussian" and asymmetry_limit <= 0.0:
        return "gaussian"
    return model


@dataclass
class SpectraDataset:
    file_path: str
    x_name: str
    spectrum_names: List[str]
    raw_df: pd.DataFrame
    x: np.ndarray


@dataclass
class ProcessedSpectra:
    x: np.ndarray
    raw: Dict[str, np.ndarray]
    filtered: Dict[str, np.ndarray]
    x1: float
    x2: float
    filter_method: FilterMethod
    filter_params: Dict[str, float]


@dataclass
class FitResult:
    model: PeakModel
    params: np.ndarray
    covariance: np.ndarray
    fitted_sum: np.ndarray
    components: np.ndarray


def load_spectra_csv(file_path: str) -> SpectraDataset:
    """Load spectrum matrix from user-selected CSV."""
    parse_errors = []
    for sep in (";", ",", "\t"):
        try:
            df = pd.read_csv(file_path, sep=sep)
            if df.shape[1] >= 2:
                break
        except Exception as exc:  # pragma: no cover
            parse_errors.append(str(exc))
            df = None
    else:
        details = " | ".join(parse_errors) if parse_errors else "unable to parse"
        raise ValueError(f"Cannot parse CSV file: {details}")

    df = df.dropna(how="all")
    if df.shape[1] < 2:
        raise ValueError("The file must have at least one X column and one spectrum column.")

    x_name = str(df.columns[0])
    spectrum_names = [str(c) for c in df.columns[1:]]

    numeric_df = df.copy()
    for col in numeric_df.columns:
        numeric_df[col] = pd.to_numeric(numeric_df[col], errors="coerce")

    numeric_df = numeric_df.dropna(axis=0, how="any")
    if numeric_df.empty:
        raise ValueError("No valid numeric rows were found in the CSV file.")

    x = numeric_df.iloc[:, 0].to_numpy(dtype=float)

    return SpectraDataset(
        file_path=file_path,
        x_name=x_name,
        spectrum_names=spectrum_names,
        raw_df=numeric_df,
        x=x,
    )


def _apply_fft_lowpass(y: np.ndarray, cutoff_ratio: float) -> np.ndarray:
    cutoff_ratio = float(np.clip(cutoff_ratio, 0.001, 0.5))
    n = y.size
    spectrum = np.fft.rfft(y)
    freq = np.fft.rfftfreq(n, d=1.0)
    max_freq = np.max(freq) if freq.size else 0.0
    if max_freq <= 0:
        return y.copy()
    threshold = cutoff_ratio * max_freq
    spectrum[freq > threshold] = 0.0
    filtered = np.fft.irfft(spectrum, n=n)
    return filtered.astype(float)


def _apply_savgol(y: np.ndarray, window_length: int, polyorder: int) -> np.ndarray:
    window_length = int(max(3, window_length))
    if window_length % 2 == 0:
        window_length += 1
    if window_length >= y.size:
        window_length = y.size - 1 if y.size % 2 == 0 else y.size
        window_length = max(3, window_length)
    polyorder = int(max(1, polyorder))
    if polyorder >= window_length:
        polyorder = max(1, window_length - 1)
    return savgol_filter(y, window_length=window_length, polyorder=polyorder).astype(float)


def apply_validity_and_filter(
    dataset: SpectraDataset,
    x1: float,
    x2: float,
    filter_method: FilterMethod,
    filter_params: Dict[str, float],
) -> ProcessedSpectra:
    """Apply user-defined X-range and denoise all spectra."""
    if x1 >= x2:
        raise ValueError("X1 must be strictly less than X2.")

    mask = (dataset.x >= x1) & (dataset.x <= x2)
    if not np.any(mask):
        raise ValueError("The selected validity range contains no data points.")

    x = dataset.x[mask]
    raw: Dict[str, np.ndarray] = {}
    filtered: Dict[str, np.ndarray] = {}

    for name in dataset.spectrum_names:
        y = dataset.raw_df[name].to_numpy(dtype=float)[mask]
        raw[name] = y

        if filter_method == "fft_lowpass":
            cutoff = float(filter_params.get("cutoff_ratio", 0.08))
            filtered[name] = _apply_fft_lowpass(y, cutoff)
        elif filter_method == "savgol":
            window = int(filter_params.get("window_length", 21))
            poly = int(filter_params.get("polyorder", 3))
            filtered[name] = _apply_savgol(y, window, poly)
        else:
            raise ValueError(f"Unsupported filter method: {filter_method}")

    return ProcessedSpectra(
        x=x,
        raw=raw,
        filtered=filtered,
        x1=float(x1),
        x2=float(x2),
        filter_method=filter_method,
        filter_params=filter_params.copy(),
    )


def detect_initial_peaks(
    x: np.ndarray,
    y: np.ndarray,
    prominence: float,
    distance: float,
) -> List[Tuple[float, float, float]]:
    """Return list of (center, amplitude, width) initial guesses."""
    peaks, props = find_peaks(y, prominence=prominence, distance=max(1, int(distance)))
    if peaks.size == 0:
        idx = int(np.argmax(y))
        fallback_width = max((x[-1] - x[0]) * 0.02, 1e-6)
        return [(float(x[idx]), float(y[idx]), float(fallback_width))]

    widths_px, _, _, _ = peak_widths(y, peaks, rel_height=0.5)
    dx = np.mean(np.diff(x)) if x.size > 1 else 1.0
    width_values = np.maximum(widths_px * max(dx, 1e-12), 1e-6)

    result: List[Tuple[float, float, float]] = []
    for i, peak_idx in enumerate(peaks):
        result.append((float(x[peak_idx]), float(y[peak_idx]), float(width_values[i])))
    return result


def expand_peaks_for_hidden_doublets(
    initial_peaks: Sequence[Tuple[float, float, float]],
    x_min: float,
    x_max: float,
    split_factor: float = 1.6,
    max_subpeaks_per_peak: int = 2,
) -> List[Tuple[float, float, float]]:
    """Split broad peaks into two initial components to capture overlapping peaks.

    A peak is split when its width is significantly larger than the median width.
    """
    if not initial_peaks:
        return []

    if max_subpeaks_per_peak <= 1:
        return [(float(c), float(a), float(w)) for c, a, w in initial_peaks]

    widths = np.array([max(float(w), 1e-9) for _, _, w in initial_peaks], dtype=float)
    median_width = float(np.median(widths)) if widths.size else 1.0
    median_width = max(median_width, 1e-9)

    expanded: List[Tuple[float, float, float]] = []
    for center, amplitude, width in initial_peaks:
        center = float(center)
        amplitude = max(float(amplitude), 1e-9)
        width = max(float(width), 1e-9)

        is_broad = width >= split_factor * median_width
        if is_broad and max_subpeaks_per_peak >= 2:
            offset = width * 0.22
            c1 = float(np.clip(center - offset, x_min, x_max))
            c2 = float(np.clip(center + offset, x_min, x_max))
            sub_width = max(width * 0.6, 1e-9)
            sub_amp = amplitude * 0.55
            expanded.append((c1, sub_amp, sub_width))
            expanded.append((c2, sub_amp, sub_width))
        else:
            expanded.append((center, amplitude, width))

    expanded.sort(key=lambda item: item[0])
    return expanded


def _aic_score(rss: float, n: int, k: int) -> float:
    rss = max(float(rss), 1e-18)
    n = max(int(n), 1)
    return n * np.log(rss / n) + 2.0 * k


def _model_param_count(model: PeakModel) -> int:
    if model == "asymmetric_gaussian":
        return 4
    return 3


def _asymmetric_widths(avg_width: float, skew: float, max_skew: float = ASYMMETRIC_MAX_SKEW) -> Tuple[float, float]:
    avg_width = max(float(avg_width), 1e-9)
    max_skew = float(max(0.0, max_skew))
    skew = float(np.clip(skew, -max_skew, max_skew))
    width_left = max(avg_width * (1.0 - skew), 1e-9)
    width_right = max(avg_width * (1.0 + skew), 1e-9)
    return width_left, width_right


def _peak_params_to_tuple(params: Sequence[float], model: PeakModel) -> Tuple[float, float, float]:
    amplitude = float(params[0])
    center = float(params[1])
    if model == "asymmetric_gaussian":
        width = float(params[2])
    else:
        width = float(params[2])
    return center, amplitude, width


def _component_area(params: Sequence[float], model: PeakModel) -> float:
    amplitude = float(params[0])
    if model == "asymmetric_gaussian":
        sigma_left, sigma_right = _asymmetric_widths(params[2], params[3])
        return amplitude * np.sqrt(np.pi / 2.0) * (sigma_left + sigma_right)
    width = float(params[2])
    return _peak_area(amplitude, width, model)


def _model_function(model: PeakModel):
    if model == "asymmetric_gaussian":
        return _multi_asymmetric_gaussian
    if model == "gaussian":
        return _multi_gaussian
    return _multi_lorentzian


def _build_initial_guess_and_bounds(
    peaks: Sequence[Tuple[float, float, float]],
    model: PeakModel,
    x_min: float,
    x_max: float,
    y_max: float,
    asymmetry_limit: float = ASYMMETRIC_MAX_SKEW,
) -> Tuple[List[float], List[float], List[float]]:
    p0: List[float] = []
    lower: List[float] = []
    upper: List[float] = []

    for center, amplitude, width in peaks:
        amp = max(float(amplitude), 1e-6)
        ctr = float(np.clip(center, x_min, x_max))
        wid = max(float(width), 1e-6)

        if model == "asymmetric_gaussian":
            skew_limit = float(max(0.0, asymmetry_limit))
            p0.extend([amp, ctr, wid, 0.0])
            lower.extend([0.0, x_min, 1e-9, -skew_limit])
            upper.extend([max(y_max * 5.0, amp * 5.0), x_max, max((x_max - x_min), wid * 10.0), skew_limit])
        else:
            p0.extend([amp, ctr, wid])
            lower.extend([0.0, x_min, 1e-9])
            upper.extend([max(y_max * 5.0, amp * 5.0), x_max, max((x_max - x_min), wid * 10.0)])

    return p0, lower, upper


def _fit_candidate_with_aic(
    x_local: np.ndarray,
    y_local: np.ndarray,
    candidate_peaks: Sequence[Tuple[float, float, float]],
    model: PeakModel,
    asymmetry_limit: float = ASYMMETRIC_MAX_SKEW,
) -> Tuple[np.ndarray, float] | None:
    if not candidate_peaks:
        return None

    x_min = float(np.min(x_local))
    x_max = float(np.max(x_local))
    y_max = max(float(np.max(y_local)), 1e-9)

    effective_model = _effective_model(model, asymmetry_limit)
    p0, lower, upper = _build_initial_guess_and_bounds(
        candidate_peaks,
        effective_model,
        x_min,
        x_max,
        y_max,
        asymmetry_limit=asymmetry_limit,
    )
    func = _model_function(effective_model)

    try:
        params, _ = curve_fit(
            func,
            x_local,
            y_local,
            p0=p0,
            bounds=(lower, upper),
            maxfev=12000,
        )
    except Exception:
        return None

    residual = y_local - func(x_local, *params)
    rss = float(np.sum(residual**2))
    aic = _aic_score(rss, x_local.size, len(params))
    return params, aic


def expand_peaks_with_local_aic(
    x: np.ndarray,
    y: np.ndarray,
    initial_peaks: Sequence[Tuple[float, float, float]],
    model: PeakModel,
    window_factor: float = 2.2,
    decision_margin: float = 2.0,
    asymmetry_limit: float = ASYMMETRIC_MAX_SKEW,
) -> List[Tuple[float, float, float]]:
    """For each detected peak, choose 1 or 2 components by local AIC comparison."""
    if not initial_peaks:
        return []

    x_min_global = float(np.min(x))
    x_max_global = float(np.max(x))
    full_span = max(x_max_global - x_min_global, 1e-9)
    min_half_window = full_span * 0.015

    effective_model = _effective_model(model, asymmetry_limit)

    refined: List[Tuple[float, float, float]] = []
    for center, amplitude, width in initial_peaks:
        center = float(center)
        amplitude = max(float(amplitude), 1e-9)
        width = max(float(width), 1e-9)

        half_window = max(width * max(window_factor, 1.1), min_half_window)
        left = center - half_window
        right = center + half_window
        mask = (x >= left) & (x <= right)

        if int(np.sum(mask)) < 10:
            refined.append((center, amplitude, width))
            continue

        x_local = x[mask]
        y_local = y[mask]

        single_candidate = [(center, amplitude, width)]

        offset = width * 0.22
        double_candidate = [
            (float(np.clip(center - offset, x_min_global, x_max_global)), amplitude * 0.55, max(width * 0.6, 1e-9)),
            (float(np.clip(center + offset, x_min_global, x_max_global)), amplitude * 0.55, max(width * 0.6, 1e-9)),
        ]

        single_fit = _fit_candidate_with_aic(
            x_local,
            y_local,
            single_candidate,
            effective_model,
            asymmetry_limit=asymmetry_limit,
        )
        double_fit = _fit_candidate_with_aic(
            x_local,
            y_local,
            double_candidate,
            effective_model,
            asymmetry_limit=asymmetry_limit,
        )

        if single_fit is None and double_fit is None:
            refined.append((center, amplitude, width))
            continue
        if single_fit is None and double_fit is not None:
            params_2, _ = double_fit
            chunk = _model_param_count(effective_model)
            refined.append(_peak_params_to_tuple(params_2[0:chunk], effective_model))
            refined.append(_peak_params_to_tuple(params_2[chunk : 2 * chunk], effective_model))
            continue
        if double_fit is None and single_fit is not None:
            params_1, _ = single_fit
            refined.append(_peak_params_to_tuple(params_1[0 : _model_param_count(effective_model)], effective_model))
            continue

        params_1, aic_1 = single_fit
        params_2, aic_2 = double_fit
        if aic_2 + decision_margin < aic_1:
            chunk = _model_param_count(effective_model)
            refined.append(_peak_params_to_tuple(params_2[0:chunk], effective_model))
            refined.append(_peak_params_to_tuple(params_2[chunk : 2 * chunk], effective_model))
        else:
            refined.append(_peak_params_to_tuple(params_1[0 : _model_param_count(effective_model)], effective_model))

    refined.sort(key=lambda item: item[0])
    return refined


def expand_peaks_with_derivative_mode(
    x: np.ndarray,
    y: np.ndarray,
    initial_peaks: Sequence[Tuple[float, float, float]],
    window_factor: float = 2.2,
    min_separation_factor: float = 0.22,
) -> List[Tuple[float, float, float]]:
    """Split hidden peaks using rapid slope change and second-derivative curvature.

    For each detected peak, a local window is analyzed. Candidate hidden centers are
    extracted from:
    - zero-crossings of first derivative (slope from + to -)
    - strong minima of second derivative (high concavity)
    """
    if not initial_peaks:
        return []

    x_min_global = float(np.min(x))
    x_max_global = float(np.max(x))
    span = max(x_max_global - x_min_global, 1e-9)
    min_half_window = span * 0.015

    refined: List[Tuple[float, float, float]] = []
    for center, amplitude, width in initial_peaks:
        center = float(center)
        amplitude = max(float(amplitude), 1e-9)
        width = max(float(width), 1e-9)

        half_window = max(width * max(window_factor, 1.1), min_half_window)
        left = center - half_window
        right = center + half_window
        mask = (x >= left) & (x <= right)

        if int(np.sum(mask)) < 10:
            refined.append((center, amplitude, width))
            continue

        x_local = x[mask]
        y_local = y[mask]

        smooth_window = max(5, int(x_local.size * 0.12))
        if smooth_window % 2 == 0:
            smooth_window += 1
        if smooth_window >= x_local.size:
            smooth_window = x_local.size - 1 if x_local.size % 2 == 0 else x_local.size
            smooth_window = max(5, smooth_window)

        poly = min(3, max(1, smooth_window - 1))
        y_smooth = savgol_filter(y_local, window_length=smooth_window, polyorder=poly)

        dy = np.gradient(y_smooth, x_local)
        d2y = np.gradient(dy, x_local)

        zero_cross_idx = np.where((dy[:-1] > 0.0) & (dy[1:] <= 0.0))[0] + 1

        d2_prom = max(float(np.std(d2y)) * 0.2, 1e-12)
        curvature_idx, _ = find_peaks(-d2y, prominence=d2_prom, distance=max(1, x_local.size // 12))

        candidate_idx = np.unique(np.concatenate([zero_cross_idx, curvature_idx]))
        if candidate_idx.size == 0:
            refined.append((center, amplitude, width))
            continue

        candidate_idx = np.array(sorted(candidate_idx, key=lambda i: y_smooth[int(i)], reverse=True), dtype=int)

        min_sep = max(width * max(min_separation_factor, 0.05), span * 0.002)
        selected: List[int] = []
        for idx in candidate_idx:
            if not selected:
                selected.append(int(idx))
                continue
            if all(abs(float(x_local[idx] - x_local[s])) >= min_sep for s in selected):
                selected.append(int(idx))
            if len(selected) >= 2:
                break

        if len(selected) >= 2:
            selected = sorted(selected[:2], key=lambda i: x_local[i])
            c1 = float(np.clip(x_local[selected[0]], x_min_global, x_max_global))
            c2 = float(np.clip(x_local[selected[1]], x_min_global, x_max_global))
            a1 = max(float(y_smooth[selected[0]]), 1e-9)
            a2 = max(float(y_smooth[selected[1]]), 1e-9)
            w = max(width * 0.6, 1e-9)
            refined.append((c1, a1, w))
            refined.append((c2, a2, w))
        else:
            idx = int(selected[0])
            c = float(np.clip(x_local[idx], x_min_global, x_max_global))
            a = max(float(y_smooth[idx]), 1e-9)
            refined.append((c, a, width))

    refined.sort(key=lambda item: item[0])
    return refined


def _smooth_local_signal(
    x_local: np.ndarray,
    y_local: np.ndarray,
    window_fraction: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    smooth_window = max(5, int(x_local.size * max(float(window_fraction), 0.06)))
    if smooth_window % 2 == 0:
        smooth_window += 1
    if smooth_window >= x_local.size:
        smooth_window = x_local.size - 1 if x_local.size % 2 == 0 else x_local.size
        smooth_window = max(5, smooth_window)

    poly = min(3, max(1, smooth_window - 1))
    y_smooth = savgol_filter(y_local, window_length=smooth_window, polyorder=poly)
    dy = np.gradient(y_smooth, x_local)
    d2y = np.gradient(dy, x_local)
    return y_smooth, dy, d2y


def _contiguous_true_segments(mask: np.ndarray) -> List[Tuple[int, int]]:
    if mask.size == 0:
        return []

    segments: List[Tuple[int, int]] = []
    start = -1
    for idx, value in enumerate(mask):
        if value and start < 0:
            start = idx
        elif not value and start >= 0:
            segments.append((start, idx - 1))
            start = -1
    if start >= 0:
        segments.append((start, mask.size - 1))
    return segments


def expand_peaks_with_plateau_edges(
    x: np.ndarray,
    y: np.ndarray,
    initial_peaks: Sequence[Tuple[float, float, float]],
    window_factor: float = 2.4,
    min_separation_factor: float = 0.24,
) -> List[Tuple[float, float, float]]:
    """Split hidden peaks by detecting left/right edges of a wide local plateau."""
    if not initial_peaks:
        return []

    x_min_global = float(np.min(x))
    x_max_global = float(np.max(x))
    span = max(x_max_global - x_min_global, 1e-9)
    min_half_window = span * 0.015

    refined: List[Tuple[float, float, float]] = []
    for center, amplitude, width in initial_peaks:
        center = float(center)
        amplitude = max(float(amplitude), 1e-9)
        width = max(float(width), 1e-9)

        half_window = max(width * max(window_factor, 1.1), min_half_window)
        left = center - half_window
        right = center + half_window
        mask = (x >= left) & (x <= right)

        if int(np.sum(mask)) < 12:
            refined.append((center, amplitude, width))
            continue

        x_local = x[mask]
        y_local = y[mask]
        y_smooth, dy, _ = _smooth_local_signal(x_local, y_local, window_fraction=0.2)

        slope_threshold = max(float(np.percentile(np.abs(dy), 30)) * 0.55, float(np.std(dy)) * 0.12, 1e-12)
        flat_mask = np.abs(dy) <= slope_threshold
        segments = _contiguous_true_segments(flat_mask)

        min_plateau_points = max(3, int(x_local.size * 0.08))
        min_plateau_span = max(width * 0.30, span * 0.0015)

        best_segment: Tuple[int, int] | None = None
        best_distance = float("inf")
        for s, e in segments:
            if (e - s + 1) < min_plateau_points:
                continue
            seg_span = float(x_local[e] - x_local[s])
            if seg_span < min_plateau_span:
                continue
            seg_center = 0.5 * float(x_local[s] + x_local[e])
            dist = abs(seg_center - center)
            if dist < best_distance:
                best_distance = dist
                best_segment = (s, e)

        if best_segment is None:
            refined.append((center, amplitude, width))
            continue

        s, e = best_segment
        min_sep = max(width * max(min_separation_factor, 0.05), span * 0.002)
        if float(x_local[e] - x_local[s]) < min_sep:
            refined.append((center, amplitude, width))
            continue

        c1 = float(np.clip(x_local[s], x_min_global, x_max_global))
        c2 = float(np.clip(x_local[e], x_min_global, x_max_global))
        a1 = max(float(y_smooth[s]), 1e-9)
        a2 = max(float(y_smooth[e]), 1e-9)
        sub_width = max(width * 0.58, 1e-9)
        refined.append((c1, a1, sub_width))
        refined.append((c2, a2, sub_width))

    refined.sort(key=lambda item: item[0])
    return refined


def expand_peaks_with_plateau_morphology(
    x: np.ndarray,
    y: np.ndarray,
    initial_peaks: Sequence[Tuple[float, float, float]],
    window_factor: float = 2.4,
    min_separation_factor: float = 0.22,
) -> List[Tuple[float, float, float]]:
    """Hybrid split using derivative cues and plateau-edge evidence in local windows."""
    if not initial_peaks:
        return []

    x_min_global = float(np.min(x))
    x_max_global = float(np.max(x))
    span = max(x_max_global - x_min_global, 1e-9)
    min_half_window = span * 0.015

    refined: List[Tuple[float, float, float]] = []
    for center, amplitude, width in initial_peaks:
        center = float(center)
        amplitude = max(float(amplitude), 1e-9)
        width = max(float(width), 1e-9)

        half_window = max(width * max(window_factor, 1.1), min_half_window)
        left = center - half_window
        right = center + half_window
        mask = (x >= left) & (x <= right)

        if int(np.sum(mask)) < 12:
            refined.append((center, amplitude, width))
            continue

        x_local = x[mask]
        y_local = y[mask]
        y_smooth, dy, d2y = _smooth_local_signal(x_local, y_local, window_fraction=0.16)

        zero_cross_idx = np.where((dy[:-1] > 0.0) & (dy[1:] <= 0.0))[0] + 1
        d2_prom = max(float(np.std(d2y)) * 0.2, 1e-12)
        curvature_idx, _ = find_peaks(-d2y, prominence=d2_prom, distance=max(1, x_local.size // 12))

        # Plateau-edge candidates from low-slope segment boundaries.
        slope_threshold = max(float(np.percentile(np.abs(dy), 30)) * 0.55, float(np.std(dy)) * 0.12, 1e-12)
        flat_mask = np.abs(dy) <= slope_threshold
        plateau_edge_idx: List[int] = []
        for s, e in _contiguous_true_segments(flat_mask):
            if (e - s + 1) >= max(3, int(x_local.size * 0.08)):
                plateau_edge_idx.append(int(s))
                plateau_edge_idx.append(int(e))

        candidate_idx = np.unique(np.concatenate([zero_cross_idx, curvature_idx, np.array(plateau_edge_idx, dtype=int)]))
        if candidate_idx.size == 0:
            refined.append((center, amplitude, width))
            continue

        # Favor strong points while allowing plateau boundaries to survive ranking.
        score = np.abs(d2y[candidate_idx]) + 0.12 * np.maximum(y_smooth[candidate_idx], 0.0)
        rank_order = np.argsort(score)[::-1]
        ranked = candidate_idx[rank_order]

        min_sep = max(width * max(min_separation_factor, 0.05), span * 0.002)
        selected: List[int] = []
        for idx in ranked:
            idx = int(idx)
            if not selected:
                selected.append(idx)
                continue
            if all(abs(float(x_local[idx] - x_local[s])) >= min_sep for s in selected):
                selected.append(idx)
            if len(selected) >= 2:
                break

        if len(selected) >= 2:
            selected = sorted(selected[:2], key=lambda i: x_local[i])
            c1 = float(np.clip(x_local[selected[0]], x_min_global, x_max_global))
            c2 = float(np.clip(x_local[selected[1]], x_min_global, x_max_global))
            a1 = max(float(y_smooth[selected[0]]), 1e-9)
            a2 = max(float(y_smooth[selected[1]]), 1e-9)
            sub_width = max(width * 0.58, 1e-9)
            refined.append((c1, a1, sub_width))
            refined.append((c2, a2, sub_width))
        else:
            idx = int(selected[0])
            c = float(np.clip(x_local[idx], x_min_global, x_max_global))
            a = max(float(y_smooth[idx]), 1e-9)
            refined.append((c, a, width))

    refined.sort(key=lambda item: item[0])
    return refined


def _multi_gaussian(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for i in range(0, len(params), 3):
        amp = params[i]
        center = params[i + 1]
        sigma = params[i + 2]
        y += amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    return y


def _multi_asymmetric_gaussian(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for i in range(0, len(params), 4):
        amp = params[i]
        center = params[i + 1]
        sigma_left, sigma_right = _asymmetric_widths(params[i + 2], params[i + 3])
        sigma = np.where(x < center, sigma_left, sigma_right)
        y += amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    return y


def _multi_lorentzian(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for i in range(0, len(params), 3):
        amp = params[i]
        center = params[i + 1]
        gamma = params[i + 2]
        y += amp / (1.0 + ((x - center) / gamma) ** 2)
    return y


def fit_spectrum(
    x: np.ndarray,
    y: np.ndarray,
    initial_peaks: Sequence[Tuple[float, float, float]],
    model: PeakModel,
    asymmetry_limit: float = ASYMMETRIC_MAX_SKEW,
) -> FitResult:
    """Fit a sum of peaks to one spectrum."""
    if not initial_peaks:
        raise ValueError("At least one initial peak is required for fitting.")

    x_min = float(np.min(x))
    x_max = float(np.max(x))
    y_max = float(np.max(y))

    effective_model = _effective_model(model, asymmetry_limit)
    p0, lower, upper = _build_initial_guess_and_bounds(
        initial_peaks,
        effective_model,
        x_min,
        x_max,
        y_max,
        asymmetry_limit=asymmetry_limit,
    )
    func = _model_function(effective_model)

    popt, pcov = curve_fit(
        func,
        x,
        y,
        p0=p0,
        bounds=(lower, upper),
        maxfev=30000,
    )

    fitted_sum = func(x, *popt)

    param_count = _model_param_count(effective_model)
    n_peaks = len(popt) // param_count
    components = np.zeros((n_peaks, x.size), dtype=float)
    for i in range(n_peaks):
        p = popt[i * param_count : (i + 1) * param_count]
        components[i] = func(x, *(p.tolist()))

    return FitResult(
        model=effective_model,
        params=popt,
        covariance=pcov,
        fitted_sum=fitted_sum,
        components=components,
    )


def fit_all_spectra(
    processed: ProcessedSpectra,
    spectrum_names: Sequence[str],
    model: PeakModel,
    prominence: float,
    distance: float,
) -> Tuple[Dict[str, FitResult], Dict[str, str]]:
    """Fit all spectra with automatic initial peak guesses."""
    fits: Dict[str, FitResult] = {}
    errors: Dict[str, str] = {}

    for name in spectrum_names:
        y = processed.filtered[name]
        try:
            initial = detect_initial_peaks(processed.x, y, prominence=prominence, distance=distance)
            fits[name] = fit_spectrum(processed.x, y, initial, model=model)
        except Exception as exc:
            errors[name] = str(exc)

    return fits, errors


def spectrum_result_dataframe(
    x: np.ndarray,
    raw: np.ndarray,
    filtered: np.ndarray,
    fit: FitResult | None,
    x_name: str = "X",
) -> pd.DataFrame:
    data = {
        x_name: x,
        "Raw": raw,
        "Filtered": filtered,
    }

    if fit is not None:
        data["Decomposed_Sum"] = fit.fitted_sum
        for i in range(fit.components.shape[0]):
            data[f"Peak_{i + 1}"] = fit.components[i]

    return pd.DataFrame(data)


def _peak_area(amplitude: float, width: float, model: PeakModel) -> float:
    if model == "gaussian":
        return amplitude * width * np.sqrt(2.0 * np.pi)
    return amplitude * np.pi * width


def peaks_summary_dataframe(fits: Dict[str, FitResult]) -> pd.DataFrame:
    rows = []
    for spectrum_name, fit in fits.items():
        param_count = _model_param_count(fit.model)
        for i in range(0, len(fit.params), param_count):
            component = fit.params[i : i + param_count]
            amp = float(component[0])
            center = float(component[1])
            row = {
                "Spectrum": spectrum_name,
                "Peak_N": (i // param_count) + 1,
                "Model": fit.model,
                "Center": center,
                "Amplitude": amp,
                "Area": _component_area(component, fit.model),
            }
            if fit.model == "asymmetric_gaussian":
                width_left, width_right = _asymmetric_widths(component[2], component[3])
                row["Width_Left"] = width_left
                row["Width_Right"] = width_right
                row["Width"] = float(component[2])
                row["Skew"] = float(component[3])
            else:
                row["Width_Left"] = float(component[2])
                row["Width_Right"] = float(component[2])
                row["Width"] = float(component[2])
                row["Skew"] = 0.0
            rows.append(row)

    return pd.DataFrame(rows)
