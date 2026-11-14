"""Частка «Підтверджено» залежно від порогу стійкості (k з 5 вікон).

Запуск: backend/.venv/bin/python tools/experiments/robust_threshold.py  (~2 хв)
Результат 14.11.2026 — у tools/experiments/README.md.
"""
import sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.verdict import evaluate_verdict

def ar1(rng, n, phi, sd):
    e = np.empty(n); e[0] = rng.normal(0, sd)
    for t in range(1, n): e[t] = phi * e[t-1] + rng.normal(0, sd * np.sqrt(1 - phi**2))
    return e

years = list(range(1981, 2026)); n = len(years); t = np.arange(n)
rows = []
for label, slope, phi, sims in [("шум, φ=0", 0.0, 0.0, 1000), ("шум, φ=0.3", 0.0, 0.3, 1000), ("шум, φ=0.5", 0.0, 0.5, 1000),
                                 ("слабкий тренд 0.02/рік", 0.02, 0.3, 400), ("середній 0.035/рік", 0.035, 0.3, 400),
                                 ("як у Києві 0.065/рік", 0.065, 0.0, 400)]:
    rng = np.random.default_rng(7)
    counts = {k: 0 for k in (0, 3, 4, 5)}
    for _ in range(sims):
        y = slope * t + ar1(rng, n, phi, 0.9)
        for k in counts:
            ev = evaluate_verdict(years, list(y), direction="increase", start_year=1981, end_year=2025,
                                  compute_wait=False, robust_need=k)
            counts[k] += ev.verdict == "confirmed"
    rows.append((label, {k: 100 * c / sims for k, c in counts.items()}))
print(f"{'ряд':24} {'без стійкості':>13} {'≥3 з 5':>8} {'≥4 з 5':>8} {'5 з 5':>8}")
for label, r in rows:
    print(f"{label:24} {r[0]:12.1f}% {r[3]:7.1f}% {r[4]:7.1f}% {r[5]:7.1f}%")
