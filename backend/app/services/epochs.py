"""Grouping exposures in time ("epochs" / "visits")."""

from __future__ import annotations

from collections.abc import Sequence


def cluster_times(times: Sequence[float], gap_days: float, max_span_days: float | None = None) -> list[list[int]]:
    """Group indices of `times` (MJD) into clusters, in time order.

    1. A new cluster starts whenever the gap to the previous (sorted) time exceeds `gap_days`.
    2. Near the ecliptic poles SPHEREx observes almost continuously (Phase 0: R Dra has
       ~2500 exposures with no 30-day gap), so any cluster longer than `max_span_days`
       (default: max(60, 2 * gap_days)) is cut into consecutive bins of `gap_days`."""
    if not times:
        return []
    if max_span_days is None:
        max_span_days = max(60.0, 2 * gap_days)
    order = sorted(range(len(times)), key=lambda i: times[i])
    groups: list[list[int]] = [[order[0]]]
    for prev, cur in zip(order, order[1:]):
        if times[cur] - times[prev] > gap_days:
            groups.append([cur])
        else:
            groups[-1].append(cur)
    out: list[list[int]] = []
    for g in groups:
        span = times[g[-1]] - times[g[0]]
        if span <= max_span_days:
            out.append(g)
            continue
        t0 = times[g[0]]
        bins: dict[int, list[int]] = {}
        for i in g:
            bins.setdefault(int((times[i] - t0) // gap_days), []).append(i)
        out.extend(bins[k] for k in sorted(bins))
    return out


def summarize_epochs(
    times: Sequence[float], t_max: Sequence[float], detectors: Sequence[int], gap_days: float
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for k, idx in enumerate(cluster_times(times, gap_days)):
        per_det: dict[str, int] = {}
        for i in idx:
            per_det[f"D{detectors[i]}"] = per_det.get(f"D{detectors[i]}", 0) + 1
        out.append({
            "index": k,
            "t_start": min(times[i] for i in idx),
            "t_end": max(t_max[i] for i in idx),
            "n_exposures": len(idx),
            "per_detector": dict(sorted(per_det.items())),
        })
    return out
