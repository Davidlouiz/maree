#!/usr/bin/env python3
"""Validation multi-ports multi-dates contre maree.info."""

import sys
sys.path.insert(0, ".")
import warnings
warnings.filterwarnings("ignore")

from maree import Maree
from datetime import datetime, timezone, timedelta, date

TZ = timezone(timedelta(hours=1))


def compare(m, refs_dict):
    """Compare predictions vs maree.info reference data."""
    results = []
    for day_str, refs in refs_dict.items():
        dd, mm = map(int, day_str.split("/"))
        for hh, mi, h_ref, kind in refs:
            dt = datetime(2026, mm, dd, hh, mi, tzinfo=TZ)
            p = m.hauteur(dt)
            results.append((day_str, kind, hh, mi, p, h_ref, p - h_ref))

    # Find predicted extremes for each day
    extremes_by_day = {}
    all_days = sorted(set(r[0] for r in results))
    for day_str in all_days:
        dd, mm = map(int, day_str.split("/"))
        _, _, extremes = m.maree_jour(
            date(2026, mm, dd), tz_offset_h=1, pas_minutes=2)
        extremes_by_day[day_str] = extremes

    return results, extremes_by_day


def print_table(port_label, source_info, results, extremes_by_day, refs_dict):
    """Print a nicely formatted comparison table."""
    print()
    print(f"  {port_label} ({source_info})")
    print("  " + "=" * 68)
    print(f"  {'Date':>5s}  {'':>2s}  {'Heure':>5s}  "
          f"{'Predit':>7s}  {'Ref':>7s}  {'Ecart':>7s}  "
          f"{'Heure pred.':>11s} {'Dt':>5s}")
    print("  " + "-" * 68)

    prev_day = None
    for day_str, kind, hh, mi, p, h_ref, ecart in results:
        if day_str != prev_day and prev_day is not None:
            print("  " + "-" * 68)
        prev_day = day_str

        # Find matching predicted extreme
        t_pred_str = ""
        dt_str = ""
        for ek, et, eh in extremes_by_day.get(day_str, []):
            if ek == kind:
                t_local = et.astimezone(TZ)
                # Check if this extreme is within ~2h of the reference time
                ref_minutes = hh * 60 + mi
                pred_minutes = t_local.hour * 60 + t_local.minute
                diff = pred_minutes - ref_minutes
                if abs(diff) < 120:
                    t_pred_str = t_local.strftime("%Hh%M")
                    dt_str = f"{diff:+d}min"
                    break

        print(f"  {day_str:>5s}  {kind:>2s}  "
              f"{hh:02d}h{mi:02d}  "
              f"{p:7.2f}m  {h_ref:7.2f}m  {ecart:+7.2f}m  "
              f"{t_pred_str:>11s} {dt_str:>5s}")

    print("  " + "=" * 68)

    # Statistics
    ecarts = [abs(r[6]) for r in results]
    print(f"  Ecart moyen : {sum(ecarts)/len(ecarts):.2f}m  "
          f"| max : {max(ecarts):.2f}m  | n={len(ecarts)}")


# ═══════════════════════════════════════════════════════════════════════════
# 1. ARCACHON — fichier td4, 105 constituants
# ═══════════════════════════════════════════════════════════════════════════
m_arc = Maree.from_td4("Arcachon.td4", lat=44.667)

arcachon_ref = {
    "09/03": [
        (2, 25, 0.95, "BM"), (8, 38, 3.67, "PM"),
        (14, 38, 1.16, "BM"), (20, 56, 3.56, "PM"),
    ],
    "12/03": [
        (4, 19, 1.71, "BM"), (11, 30, 2.85, "PM"), (16, 53, 1.91, "BM"),
    ],
    "15/03": [
        (2, 54, 3.45, "PM"), (8, 56, 1.23, "BM"),
        (15, 26, 3.47, "PM"), (21, 19, 1.19, "BM"),
    ],
}

res_a, ext_a = compare(m_arc, arcachon_ref)
print_table("ARCACHON", "td4, 105 constituants", res_a, ext_a, arcachon_ref)

# ═══════════════════════════════════════════════════════════════════════════
# 2. BREST — atlas V1_FINIS, 37 constituants
# ═══════════════════════════════════════════════════════════════════════════
m_brest = Maree.from_atlas(
    "MARC_L1-ATLAS-AHRMONIQUES/V1_FINIS",
    lat=48.375, lon=-4.500, z0=4.10)

brest_ref = {
    "09/03": [
        (2, 20, 2.05, "BM"), (8, 8, 6.07, "PM"),
        (14, 34, 2.36, "BM"), (20, 24, 5.85, "PM"),
    ],
    "12/03": [
        (4, 38, 3.26, "BM"), (10, 36, 4.77, "PM"),
        (17, 18, 3.49, "BM"), (23, 44, 4.86, "PM"),
    ],
    "15/03": [
        (2, 32, 5.50, "PM"), (8, 53, 2.61, "BM"),
        (15, 3, 5.60, "PM"), (21, 15, 2.46, "BM"),
    ],
}

res_b, ext_b = compare(m_brest, brest_ref)
print_table("BREST", "atlas V1_FINIS, Z0=4.10m", res_b, ext_b, brest_ref)

# ═══════════════════════════════════════════════════════════════════════════
# 3. DAHOUET — atlas V1_MANE
# ═══════════════════════════════════════════════════════════════════════════
m_dah = Maree.from_atlas(
    "MARC_L1-ATLAS-AHRMONIQUES/V1_MANW",
    lat=48.583, lon=-2.567, z0=6.32)

dahouet_ref = {
    "09/03": [
        (4, 29, 2.76, "BM"), (10, 5, 9.81, "PM"),
        (16, 38, 3.20, "BM"), (22, 17, 9.51, "PM"),
    ],
    "15/03": [
        (4, 35, 8.54, "PM"), (11, 6, 3.89, "BM"),
        (17, 4, 8.86, "PM"), (23, 32, 3.68, "BM"),
    ],
}

res_d, ext_d = compare(m_dah, dahouet_ref)
print_table("DAHOUET", f"{m_dah.name}, Z0=6.32m", res_d, ext_d, dahouet_ref)

# ═══════════════════════════════════════════════════════════════════════════
# 4. LE CROTOY — atlas V0_MANGA or V0_ATLNE
# ═══════════════════════════════════════════════════════════════════════════
m_cro = Maree.from_atlas(
    "MARC_L1-ATLAS-AHRMONIQUES/V0_MANGA",
    lat=50.233, lon=1.467, z0=5.5)

crotoy_ref = {
    "09/03": [
        (2, 51, 9.02, "PM"), (9, 45, 2.09, "BM"),
        (15, 4, 8.66, "PM"), (21, 57, 2.35, "BM"),
    ],
    "15/03": [
        (3, 52, 3.42, "BM"), (9, 24, 7.61, "PM"),
        (16, 21, 2.93, "BM"), (21, 50, 7.99, "PM"),
    ],
}

res_c, ext_c = compare(m_cro, crotoy_ref)
print_table("LE CROTOY", f"{m_cro.name}, Z0=5.5m", res_c, ext_c, crotoy_ref)

# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
print("\n")
print("  RESUME GLOBAL")
print("  " + "=" * 58)
print(f"  {'Port':>12s}  {'Source':>20s}  {'Ecart moy':>10s}  {'Ecart max':>10s}")
print("  " + "-" * 58)
for label, res in [("Arcachon", res_a), ("Brest", res_b),
                   ("Dahouet", res_d), ("Le Crotoy", res_c)]:
    ecarts = [abs(r[6]) for r in res]
    src = "td4" if label == "Arcachon" else "atlas"
    print(f"  {label:>12s}  {src:>20s}  "
          f"{sum(ecarts)/len(ecarts):10.2f}m  {max(ecarts):10.2f}m")
print("  " + "=" * 58)
