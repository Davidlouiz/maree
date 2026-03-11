"""
maree.py — Bibliothèque de prédiction de marées par analyse harmonique.

Prédit la hauteur d'eau en mètres au-dessus du zéro des cartes pour une
date/heure et une position donnée, en utilisant les constantes harmoniques
issues des atlas MARC/SHOM ou de fichiers .td4 (format COMODO).

Sources de données supportées
─────────────────────────────
  • Fichiers .td4 — constantes harmoniques par port (format SHOM/COMODO)
  • Atlas harmoniques NetCDF — grilles MARC/SHOM, pour positions arbitraires

Formule de prédiction
─────────────────────
  h(t) = Z0 + Σ fₙ · Hₙ · cos(Vₙ(t) + uₙ − Gₙ)

  où fₙ = facteur nodal (amplitude), uₙ = correction nodale (phase),
  Vₙ = argument astronomique, Gₙ = phase de Greenwich du constituant,
  Hₙ = amplitude.  Les arguments astronomiques et corrections nodales
  sont calculés via utide (convention Doodson/Schureman, sans correction
  « semi » de Foreman).

Usage rapide
────────────
    from maree import Maree
    from datetime import datetime, timezone

    m = Maree.from_td4("Arcachon.td4", lat=44.667)
    h = m.hauteur(datetime(2026, 3, 9, 7, 38, tzinfo=timezone.utc))
    # → hauteur en mètres au-dessus du zéro des cartes

Précision
─────────
  Les constantes harmoniques proviennent du modèle MARS2D (PREVIMER).
  La précision dépend de la zone :
    • Ports en eau libre (Brest, Saint-Malo) : ~10-15 cm RMS
    • Bassins semi-fermés (Arcachon) : ~25 cm RMS, déconseillé par le SHOM

  Pour une meilleure précision, utiliser les constantes harmoniques
  officielles du SHOM (annuaire des marées, SHOMAR).
"""

import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Union
import warnings

# ─────────────────────────────────────────────────────────────────────────────
# Utide : calcul des arguments astronomiques (F, U, V)
# ─────────────────────────────────────────────────────────────────────────────
from utide import ut_constants
from utide.harmonics import FUV

_CONST = ut_constants.const
_UTIDE_NAMES = list(_CONST.name)

# ─────────────────────────────────────────────────────────────────────────────
# Correspondance noms SHOM / td4 / atlas  →  noms utide
# ─────────────────────────────────────────────────────────────────────────────
_SHOM_TO_UTIDE = {
    # —— Diurnaux ——
    "SIGMA1": "SIG1",
    "Sig1": "SIG1",
    "RHO1": "RHO1",
    "Ro1": "RHO1",
    "THETA1": "THE1",
    "Tta1": "THE1",
    "CHI1": "CHI1",
    "Ki1": "CHI1",
    "PI1": "PI1",
    "Pi1": "PI1",
    "PHI1": "PHI1",
    "Phi1": "PHI1",
    "PSI1": "PSI1",
    "Psi1": "PSI1",
    # —— Semi-diurnaux ——
    "GAMMA2": "GAM2",
    "LAMBDA2": "LDA2",
    "La2": "LDA2",
    "KJ2": "ETA2",  # η₂
    "E2": "EPS2",  # ε₂
    "Mu2": "MU2",
    "Nu2": "NU2",
    # —— Identiques (noms SHOM == utide) ——
    "Z0": "Z0",
    "SA": "SA",
    "SSA": "SSA",
    "MSM": "MSM",
    "MM": "MM",
    "Mm": "MM",
    "MSF": "MSF",
    "MF": "MF",
    "Mf": "MF",
    "2Q1": "2Q1",
    "Q1": "Q1",
    "O1": "O1",
    "P1": "P1",
    "S1": "S1",
    "K1": "K1",
    "J1": "J1",
    "OO1": "OO1",
    "M1": None,
    "MP1": None,
    "MS1": None,
    "KQ1": None,
    "2N2": "2N2",
    "MU2": "MU2",
    "N2": "N2",
    "NU2": "NU2",
    "M2": "M2",
    "L2": "L2",
    "T2": "T2",
    "S2": "S2",
    "R2": "R2",
    "K2": "K2",
    "2NS2": "2NS2",
    "OQ2": "OQ2",
    "OP2": "OP2",
    "MKS2": "MKS2",
    "MSN2": "MSN2",
    "2SM2": "2SM2",
    "SKM2": "SKM2",
    # —— Composés / shallow water ——
    "M3": "M3",
    "MK3": "MK3",
    "SO3": "SO3",
    "SP3": "SP3",
    "SK3": "SK3",
    "N4": "N4",
    "3MS4": "3MS4",
    "MN4": "MN4",
    "M4": "M4",
    "MK4": "MK4",
    "SN4": "SN4",
    "MS4": "MS4",
    "S4": "S4",
    "SK4": "SK4",
    "2NM6": "2NM6",
    "2MN6": "2MN6",
    "M6": "M6",
    "MSN6": "MSN6",
    "MKN6": "MKN6",
    "2MS6": "2MS6",
    "2MK6": "2MK6",
    "2SM6": "2SM6",
    "MSK6": "MSK6",
    "3MN8": "3MN8",
    "M8": "M8",
    "3MS8": "3MS8",
    "3MK8": "3MK8",
}

# Constituants non répertoriés par utide → vitesse angulaire + décomposition
# permettant de recalculer f et u à partir des constituants parents.
_EXTRA_CONSTITUENTS = {
    # Semi-diurnaux composés
    "M(SK)2": (29.0662416, [("M2", 1), ("S2", 1), ("K2", -1)]),
    "M(KS)2": (28.9019669, [("M2", 1), ("K2", 1), ("S2", -1)]),
    "NKM2": (28.9019669, [("N2", 1), ("K2", 1), ("M2", -1)]),
    "MNS2": (27.4238337, [("M2", 1), ("N2", 1), ("S2", -1)]),
    "MNUS2": (27.4966873, [("M2", 1), ("NU2", 1), ("S2", -1)]),
    "2MK2": (27.8860711, [("M2", 2), ("K2", -1)]),
    "2MN2S2": (26.4079380, [("M2", 2), ("N2", 1), ("S2", -2)]),
    "3M2S2": (26.8712065, [("M2", 3), ("S2", -2)]),
    # Diurnaux composés
    "MS1": (14.4966878, [("M2", 1), ("S2", -1), ("K1", 1)]),
    "MP1": (14.0251728, [("M2", 1), ("P1", -1)]),
    "KQ1": (13.4715145, [("K1", 1), ("Q1", 1), ("O1", -1)]),
    "M1": (14.4920521, [("M2", 0.5)]),
    # Terdiurnaux
    "2MK3": (42.9271398, [("M2", 2), ("K1", -1)]),
    "S3": (45.0, []),
    # Quart-diurnaux composés
    "2MMUS4": (55.9364170, [("M2", 2), ("MU2", 1), ("S2", -1)]),
    "2MNS4": (56.4079380, [("M2", 2), ("N2", 1), ("S2", -1)]),
    "MNU4": (57.4966873, [("M2", 1), ("NU2", 1)]),
    "2MSK4": (57.8860711, [("M2", 2), ("S2", 1), ("K2", -1)]),
    "2MKS4": (57.8860711, [("M2", 2), ("K2", 1), ("S2", -1)]),
    "3MN4": (57.4238337, [("M2", 3), ("N2", -1)]),
    "NK4": (58.5218669, [("N2", 1), ("K2", 1)]),
    "MT4": (57.4966873, [("M2", 1), ("T2", 1)]),
    "2SNM4": (59.5284789, [("S2", 2), ("N2", 1), ("M2", -1)]),
    "2MSN4": (58.5125831, [("M2", 2), ("S2", 1), ("N2", -1)]),
    # Sixième-diurnaux composés
    "3MNK6": (86.3257952, [("M2", 3), ("N2", 1), ("K2", -1)]),
    "3MNS6": (85.3920423, [("M2", 3), ("N2", 1), ("S2", -1)]),
    "3MNUS6": (85.4648959, [("M2", 3), ("NU2", 1), ("S2", -1)]),
    "4MK6": (85.8542797, [("M2", 4), ("K2", -1)]),
    "4MS6": (85.9364170, [("M2", 4), ("S2", -1)]),
    "2MNU6": (86.4808916, [("M2", 2), ("NU2", 1)]),
    "3MSK6": (86.8702754, [("M2", 3), ("S2", 1), ("K2", -1)]),
    "3MKS6": (86.8702754, [("M2", 3), ("K2", 1), ("S2", -1)]),
    "4MN6": (87.4238338, [("M2", 4), ("N2", -1)]),
    "MNK6": (87.5059711, [("M2", 1), ("N2", 1), ("K2", 1)]),
    "2SN6": (88.4397296, [("S2", 2), ("N2", 1)]),
    "3MSN6": (87.4966873, [("M2", 3), ("S2", 1), ("N2", -1)]),
    "3MKN6": (87.5059711, [("M2", 3), ("K2", 1), ("N2", -1)]),
    # Huitième-diurnaux composés
    "3MNU8": (115.4648959, [("M2", 3), ("NU2", 1)]),
    "2MSN8": (116.4966873, [("M2", 2), ("S2", 1), ("N2", 1)]),
    "2(MS)8": (117.9682085, [("M2", 2), ("S2", 2)]),
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────


def _datetime_to_ordinal(dt: datetime) -> float:
    """
    Convertit un datetime (UTC) en ordinal Python + fraction de jour.

    IMPORTANT : utide ut_astron attend des ordinaux Python (jours depuis l'an 1),
    PAS les datenums matplotlib.  Depuis matplotlib >= 3.3, date2num utilise
    l'époque 1970 alors que utide utilise l'époque ordinale (693595.5 = 1899-12-31
    à midi).  Utiliser date2num provoquerait un décalage de ~719 163 jours !
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return (
        dt.toordinal()
        + dt.hour / 24.0
        + dt.minute / 1440.0
        + dt.second / 86400.0
        + dt.microsecond / 86400e6
    )


def _datetime_to_jd(dt: datetime) -> float:
    """Convertit un datetime (naif = UTC) en Jour Julien."""
    y, m = dt.year, dt.month
    d = dt.day + dt.hour / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0
    if m <= 2:
        y -= 1
        m += 12
    A = int(y / 100)
    B = 2 - A + int(A / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


# ─────────────────────────────────────────────────────────────────────────────
# Classe principale
# ─────────────────────────────────────────────────────────────────────────────


class Maree:
    """
    Prediction de maree par methode harmonique.

    Le Z0 (niveau moyen au-dessus du zero des cartes) est calcule
    automatiquement a partir des harmoniques : c'est l'oppose du
    minimum astronomique sur 18.6 ans (LAT = Lowest Astronomical Tide),
    qui est par definition le zero hydrographique.

    Attributes
    ----------
    z0 : float
        Niveau moyen au-dessus du zero des cartes (metres).
        Calcule automatiquement si non fourni.
    constituents : dict
        ``{nom: (amplitude_m, phase_greenwich_deg)}`` pour chaque constituant.
    name : str
        Nom du port ou description de la source.
    lat : float
        Latitude (pour le calcul des corrections nodales).
    """

    def __init__(
        self,
        constituents: dict,
        name: str = "",
        lat: float = 48.0,
        z0: Optional[float] = None,
    ):
        self.constituents = constituents
        self.name = name
        self.lat = lat
        self._prepare()
        self.z0 = z0 if z0 is not None else self._compute_z0()

    # ── Preparation interne ─────────────────────────────────────────────

    def _prepare(self):
        """Separe les constituants utide / extra / ignores."""
        self._utide_names = []
        self._utide_indices = []
        self._utide_amp = []
        self._utide_phase = []

        self._extra_names = []
        self._extra_amp = []
        self._extra_phase = []
        self._extra_speed = []
        self._extra_decomp = []

        self._skipped = []

        for shom_name, (amp, phase) in self.constituents.items():
            if shom_name == "Z0":
                continue

            utide_name = _SHOM_TO_UTIDE.get(shom_name, shom_name)

            if utide_name is not None and utide_name in _UTIDE_NAMES:
                self._utide_names.append(utide_name)
                self._utide_indices.append(_UTIDE_NAMES.index(utide_name))
                self._utide_amp.append(amp)
                self._utide_phase.append(phase)
            elif shom_name in _EXTRA_CONSTITUENTS:
                speed, decomp = _EXTRA_CONSTITUENTS[shom_name]
                self._extra_names.append(shom_name)
                self._extra_amp.append(amp)
                self._extra_phase.append(phase)
                self._extra_speed.append(speed)
                self._extra_decomp.append(decomp)
            else:
                self._skipped.append((shom_name, amp))

        self._utide_indices = np.array(self._utide_indices, dtype=int)
        self._utide_amp = np.array(self._utide_amp)
        self._utide_phase = np.array(self._utide_phase)
        self._extra_amp = np.array(self._extra_amp) if self._extra_amp else np.array([])
        self._extra_phase = (
            np.array(self._extra_phase) if self._extra_phase else np.array([])
        )
        self._extra_speed = (
            np.array(self._extra_speed) if self._extra_speed else np.array([])
        )

        if self._skipped:
            total = sum(a for _, a in self._skipped)
            warnings.warn(
                f"Constituants ignores ({len(self._skipped)}, "
                f"amp totale={total:.4f}m): "
                + ", ".join(f"{n}({a:.4f})" for n, a in self._skipped)
            )

    # ── Calcul automatique du Z0 ────────────────────────────────────────

    def _compute_z0(self, years: float = 18.61, dt_min: int = 6) -> float:
        """
        Calcule Z0 = -LAT (Lowest Astronomical Tide) sur un cycle nodal.

        Le zero hydrographique (zero des cartes) est defini comme le LAT,
        c'est-a-dire le minimum absolu de la maree astronomique sur 18.6 ans.
        Par definition h(t_LAT) = 0, donc Z0 = -min(partie oscillante).

        Parameters
        ----------
        years : float
            Duree de simulation (defaut 18.61 ans = 1 cycle nodal complet).
        dt_min : int
            Pas de temps en minutes (defaut 6 = precision ~1 cm).

        Returns
        -------
        float
            Z0 en metres.
        """
        if len(self._utide_indices) == 0:
            return 0.0

        t0 = datetime(2006, 1, 1)  # naive UTC
        total_minutes = int(years * 365.25 * 24 * 60)

        const = _CONST
        speeds = const.freq[self._utide_indices] * 360.0  # deg/h
        amp = self._utide_amp
        phase_g = self._utide_phase

        chunk_days = 30
        chunk_minutes = chunk_days * 24 * 60
        global_min = np.inf

        minute = 0
        while minute < total_minutes:
            chunk_size = min(chunk_minutes, total_minutes - minute)
            n_pts = chunk_size // dt_min

            t_mid = t0 + timedelta(minutes=minute + chunk_size // 2)
            t_ord = _datetime_to_ordinal(t_mid)

            F, U, V = FUV(
                t_ord,
                t_ord,
                self._utide_indices,
                self.lat,
                ngflgs=[0, 0, 0, 0],
            )
            f = F.flatten()
            u = U.flatten() * 360.0
            v0 = V.flatten() * 360.0

            hours = np.arange(n_pts) * (dt_min / 60.0) - (chunk_size / 60.0 / 2.0)

            phases_deg = (
                (v0 + u)[np.newaxis, :]
                + speeds[np.newaxis, :] * hours[:, np.newaxis]
                - phase_g[np.newaxis, :]
            )
            h_osc = np.sum(
                f[np.newaxis, :] * amp[np.newaxis, :] * np.cos(np.deg2rad(phases_deg)),
                axis=1,
            )

            chunk_min = float(np.min(h_osc))
            if chunk_min < global_min:
                global_min = chunk_min

            minute += chunk_minutes

        return float(-global_min)

    # ── Prediction ──────────────────────────────────────────────────────

    def hauteur(
        self, dt: Union[datetime, list[datetime], np.ndarray]
    ) -> Union[float, np.ndarray]:
        """
        Predit la hauteur d'eau en metres au-dessus du zero des cartes.

        Parameters
        ----------
        dt : datetime ou liste de datetime
            Date/heure UTC.  Accepte les datetime timezone-aware (convertis
            en UTC) ou naifs (consideres UTC).

        Returns
        -------
        float ou np.ndarray
            Hauteur(s) en metres.
        """
        scalar = isinstance(dt, datetime)
        if scalar:
            dt = [dt]

        heights = np.empty(len(dt))
        for i, t in enumerate(dt):
            heights[i] = self._predict_single(t)

        return float(heights[0]) if scalar else heights

    def _predict_single(self, dt: datetime) -> float:
        """Predit la hauteur pour un instant unique."""
        if dt.tzinfo is not None:
            dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            dt_utc = dt

        t_ord = _datetime_to_ordinal(dt_utc)
        h = self.z0

        # ── Constituants utide ──
        if len(self._utide_indices) > 0:
            F, U, V = FUV(
                t_ord, t_ord, self._utide_indices, self.lat, ngflgs=[0, 0, 0, 0]
            )
            F = F.flatten()
            U = U.flatten() * 360.0  # cycles -> degres
            V = V.flatten() * 360.0
            phase_rad = np.deg2rad(V + U - self._utide_phase)
            h += np.sum(F * self._utide_amp * np.cos(phase_rad))

        # ── Constituants extra ──
        if len(self._extra_amp) > 0:
            h += self._predict_extra(dt_utc, t_ord)

        return h

    def _predict_extra(self, dt_utc: datetime, t_ord: float) -> float:
        """Predit la contribution des constituants absents d'utide."""
        parent_set = set()
        for decomp in self._extra_decomp:
            for pname, _ in decomp:
                if pname in _UTIDE_NAMES:
                    parent_set.add(pname)

        parent_data = {}
        if parent_set:
            parent_list = sorted(parent_set)
            parent_idx = np.array([_UTIDE_NAMES.index(n) for n in parent_list])
            F_p, U_p, V_p = FUV(t_ord, t_ord, parent_idx, self.lat, ngflgs=[0, 0, 0, 0])
            F_p = F_p.flatten()
            U_p = U_p.flatten() * 360.0
            V_p = V_p.flatten() * 360.0
            for j, pname in enumerate(parent_list):
                parent_data[pname] = (F_p[j], U_p[j], V_p[j])

        jd = _datetime_to_jd(dt_utc)
        t_hours = (jd - 2451545.0) * 24.0

        total = 0.0
        for k in range(len(self._extra_amp)):
            decomp = self._extra_decomp[k]
            amp = self._extra_amp[k]
            phase_g = self._extra_phase[k]

            V_c, U_c, f_c = 0.0, 0.0, 1.0
            if decomp:
                for pname, coef in decomp:
                    if pname in parent_data:
                        f_p, u_p, v_p = parent_data[pname]
                        V_c += coef * v_p
                        U_c += coef * u_p
                        f_c *= f_p ** abs(coef)
            else:
                V_c = self._extra_speed[k] * t_hours
                f_c = 1.0

            total += f_c * amp * np.cos(np.deg2rad(V_c + U_c - phase_g))

        return total

    # ── Affichage / analyse ─────────────────────────────────────────────

    def maree_jour(self, date, tz_offset_h: int = 1, pas_minutes: int = 5):
        """
        Affiche le maregramme d'une journee avec pleines et basses mers.

        Parameters
        ----------
        date : datetime.date ou datetime
            Le jour a afficher.
        tz_offset_h : int
            Decalage horaire par rapport a UTC (1 = hiver, 2 = ete).
        pas_minutes : int
            Pas de temps en minutes (defaut 5).

        Returns
        -------
        tuple : (times, heights, extremes)
        """
        from datetime import date as date_type

        if isinstance(date, date_type) and not isinstance(date, datetime):
            date = datetime(date.year, date.month, date.day)

        tz = timezone(timedelta(hours=tz_offset_h))
        start = datetime(date.year, date.month, date.day, 0, 0, tzinfo=tz)
        n_steps = 24 * 60 // pas_minutes + 1
        times = [start + timedelta(minutes=i * pas_minutes) for i in range(n_steps)]
        heights = np.asarray(self.hauteur(times))

        extremes = []
        for i in range(1, len(heights) - 1):
            if heights[i] > heights[i - 1] and heights[i] > heights[i + 1]:
                extremes.append(("PM", times[i], heights[i]))
            elif heights[i] < heights[i - 1] and heights[i] < heights[i + 1]:
                extremes.append(("BM", times[i], heights[i]))

        tz_name = f"UTC{tz_offset_h:+d}"
        print(f"\n{'=' * 55}")
        print(f"  Marees a {self.name} — {date.strftime('%d/%m/%Y')}")
        print(f"  (heures {tz_name})")
        print(f"{'=' * 55}")
        for kind, t, h in extremes:
            label = "Pleine Mer" if kind == "PM" else "Basse Mer "
            t_local = t.astimezone(tz)
            print(f"  {label}  {t_local.strftime('%Hh%M')}  —  {h:.2f} m")
        print(f"{'=' * 55}\n")

        return times, heights, extremes

    # ── Constructeurs ───────────────────────────────────────────────────

    @classmethod
    def from_td4(cls, filepath: str, lat: Optional[float] = None) -> "Maree":
        """
        Charge les constantes harmoniques depuis un fichier .td4.

        La ligne METRIC du fichier est analysee pour detecter un eventuel
        decalage de fuseau horaire sur les phases (ex: ``+1.00`` = UTC+1).
        Les phases sont automatiquement converties en UTC (Greenwich).

        Parameters
        ----------
        filepath : str
            Chemin vers le fichier .td4.
        lat : float, optional
            Latitude du port.  Par defaut 48.0 (cote atlantique francaise).
        """
        fpath = Path(filepath)
        constituents = {}
        name = fpath.stem
        name_set = False
        tz_offset_h = 0.0  # timezone offset from METRIC line

        with open(fpath, "r", encoding="latin-1") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("METRIC"):
                # Format: METRIC  a  b  c  tz_offset
                # The last value is the timezone offset (hours from UTC)
                mparts = line.split()
                if len(mparts) >= 5:
                    try:
                        tz_offset_h = float(mparts[4])
                    except ValueError:
                        pass
                continue
            if line.startswith('"'):
                candidate = line.strip('"').strip()
                if candidate and not name_set:
                    name = candidate
                    name_set = True
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            cname = parts[0]
            try:
                if cname == "Z0":
                    pass  # Z0 calcule automatiquement
                elif len(parts) >= 3:
                    constituents[cname] = (float(parts[1]), float(parts[2]))
            except ValueError:
                continue

        # Convert phases from local time to UTC if timezone offset is set
        if tz_offset_h != 0.0:
            constituents = cls._correct_phases_tz(constituents, tz_offset_h)

        return cls(
            constituents=constituents,
            name=name,
            lat=lat if lat is not None else 48.0,
        )

    @classmethod
    def from_har(cls, filepath: str) -> "Maree":
        """
        Charge les constantes harmoniques depuis un fichier ``.har``.

        Format INI simplifie avec deux sections :

        .. code-block:: ini

            [port]
            nom       = Port-en-Bessin
            latitude  = 49.35
            longitude = -0.75

            [constituants]
            # nom    amplitude(m)   phase(°)
            M2       2.324588       272.4855

        Le Z0 est calcule automatiquement (LAT sur 18.6 ans).
        Les phases sont referencees a Greenwich (UTC), convention
        Doodson/Schureman.

        Parameters
        ----------
        filepath : str
            Chemin vers le fichier ``.har``.
        """
        fpath = Path(filepath)
        constituents = {}
        name = fpath.stem
        lat = 48.0
        z0_from_file = None
        section = None

        with open(fpath, "r", encoding="utf-8") as f:
            pending_section = None
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Handle section headers, possibly split across lines:
                # [port]  or  [port\n]
                if line.startswith("["):
                    if line.endswith("]"):
                        section = line[1:-1].lower()
                    else:
                        pending_section = line[1:]
                    continue
                if pending_section is not None:
                    if line == "]":
                        section = pending_section.lower()
                        pending_section = None
                        continue
                    else:
                        pending_section = None
                if section == "port":
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip().lower()
                        val = val.strip()
                        if key == "nom":
                            name = val
                        elif key == "latitude":
                            lat = float(val)
                        elif key == "longitude":
                            pass  # informational
                        elif key == "z0":
                            try:
                                z0_from_file = float(val)
                            except ValueError:
                                pass
                elif section == "constituants":
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            constituents[parts[0]] = (
                                float(parts[1]),
                                float(parts[2]),
                            )
                        except ValueError:
                            continue

        return cls(constituents=constituents, name=name, lat=lat, z0=z0_from_file)

    @staticmethod
    def _correct_phases_tz(constituents: dict, tz_offset_h: float) -> dict:
        """
        Convertit les phases de temps local en UTC (Greenwich).

        G_utc = G_local - vitesse_deg_h × decalage_horaire

        Parameters
        ----------
        constituents : dict
            {nom: (amplitude, phase_locale_deg)}
        tz_offset_h : float
            Decalage horaire (ex: +1.0 pour UTC+1).
        """
        corrected = {}
        for cname, (amp, phase) in constituents.items():
            # Find angular speed for this constituent
            utide_name = _SHOM_TO_UTIDE.get(cname, cname)
            speed_deg_h = 0.0

            if utide_name and utide_name in _UTIDE_NAMES:
                idx = _UTIDE_NAMES.index(utide_name)
                speed_deg_h = _CONST.freq[idx] * 360.0  # cycles/h -> deg/h
            elif cname in _EXTRA_CONSTITUENTS:
                speed_deg_h = _EXTRA_CONSTITUENTS[cname][0]

            corrected[cname] = (amp, phase - speed_deg_h * tz_offset_h)

        return corrected

    @classmethod
    def from_atlas(
        cls,
        atlas_dir: str,
        lat: float,
        lon: float,
    ) -> "Maree":
        """
        Charge les constantes depuis les atlas NetCDF SHOM/MARC.

        Utilise le plus proche voisin **valide** (ocean, non masque).
        Le Z0 est calcule automatiquement (LAT sur 18.6 ans).

        Parameters
        ----------
        atlas_dir : str
            Repertoire contenant les fichiers ``*-XE-*-atlas.nc``.
        lat, lon : float
            Position (degres decimaux, ouest = negatif).
        """
        import netCDF4

        adir = Path(atlas_dir)
        xe_files = sorted(adir.glob("*-XE-*-atlas.nc"))
        if not xe_files:
            raise FileNotFoundError(f"Aucun fichier *-XE-* dans {adir}")

        # Trouver le fichier M2 pour le masque terre/mer
        m2_file = next((f for f in xe_files if f.name.startswith("M2-")), xe_files[0])

        ds0 = netCDF4.Dataset(str(m2_file))
        grid_lat = ds0.variables["latitude"][:]
        grid_lon = ds0.variables["longitude"][:]
        amp0 = ds0.variables["XE_a"][:]
        ds0.close()

        dist = (grid_lat - lat) ** 2 + (grid_lon - lon) ** 2
        ocean_mask = ~np.ma.getmaskarray(amp0)
        valid_dist = np.where(ocean_mask, dist, 1e10)
        idx = np.unravel_index(np.argmin(valid_dist), valid_dist.shape)

        if valid_dist[idx] > 1e9:
            raise ValueError(f"Aucun point oceanique pres de ({lat:.3f}, {lon:.3f})")

        actual_lat = float(grid_lat[idx])
        actual_lon = float(grid_lon[idx])
        dist_deg = float(np.sqrt(valid_dist[idx]))

        if dist_deg > 0.1:
            warnings.warn(
                f"Point oceanique le plus proche a {dist_deg:.3f} deg "
                f"de ({lat:.3f}, {lon:.3f}) -> "
                f"({actual_lat:.3f}, {actual_lon:.3f})"
            )

        constituents = {}
        for f in xe_files:
            cname = f.name.split("-XE-")[0]
            if cname == "Z0":
                continue

            ds = netCDF4.Dataset(str(f))
            a = ds.variables["XE_a"][idx]
            p = ds.variables["XE_G"][idx]
            ds.close()

            if np.ma.is_masked(a) or np.ma.is_masked(p):
                continue
            a, p = float(a), float(p)
            if np.isnan(a) or np.isnan(p):
                continue

            constituents[cname] = (a, p)

        atlas_name = adir.name
        desc = f"Atlas {atlas_name} @ ({actual_lat:.3f}N, {actual_lon:.3f}E)"

        return cls(constituents=constituents, name=desc, lat=lat)

    @classmethod
    def from_atlas_auto(
        cls,
        atlas_base_dir: str,
        lat: float,
        lon: float,
    ) -> "Maree":
        """
        Selectionne automatiquement le meilleur atlas (resolution la plus
        fine) couvrant la position demandee.
        Le Z0 est calcule automatiquement (LAT sur 18.6 ans).

        Parameters
        ----------
        atlas_base_dir : str
            Repertoire parent (ex. ``MARC_L1-ATLAS-AHRMONIQUES``).
        lat, lon : float
            Position geographique.
        """
        import netCDF4

        base = Path(atlas_base_dir)
        # V1 (haute resolution) avant V0 (basse resolution)
        atlas_dirs = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)

        best = None
        best_dist = 1e10

        for ad in atlas_dirs:
            xe_files = list(ad.glob("*-XE-*-atlas.nc"))
            if not xe_files:
                continue

            m2_file = next(
                (f for f in xe_files if f.name.startswith("M2-")), xe_files[0]
            )

            ds = netCDF4.Dataset(str(m2_file))
            glat = ds.variables["latitude"][:]
            glon = ds.variables["longitude"][:]
            amp = ds.variables["XE_a"][:]
            ds.close()

            dist = (glat - lat) ** 2 + (glon - lon) ** 2
            ocean = ~np.ma.getmaskarray(amp)
            vd = np.where(ocean, dist, 1e10)
            min_idx = np.unravel_index(np.argmin(vd), vd.shape)
            d = float(vd[min_idx])

            if d < best_dist:
                best_dist = d
                best = ad

        if best is None:
            raise ValueError(f"Aucun atlas ne couvre ({lat:.3f}, {lon:.3f})")

        return cls.from_atlas(str(best), lat, lon)


# ─────────────────────────────────────────────────────────────────────────────
# Fonction utilitaire de haut niveau
# ─────────────────────────────────────────────────────────────────────────────


def hauteur_eau(
    latitude: float,
    longitude: float,
    dateheure: datetime,
    td4_file: Optional[str] = None,
    atlas_dir: Optional[str] = None,
    atlas_base_dir: Optional[str] = None,
) -> float:
    """
    Predit la hauteur d'eau en metres au-dessus du zero des cartes.

    Le Z0 est calcule automatiquement a partir des harmoniques (LAT).

    Parameters
    ----------
    latitude, longitude : float
        Position (degres decimaux, ouest = negatif).
    dateheure : datetime
        Date/heure.  Si timezone-aware, converti en UTC.
        Si naif (sans tzinfo), considere comme UTC.
    td4_file : str, optional
        Chemin vers un fichier .td4 pour un port connu.
    atlas_dir : str, optional
        Repertoire d'un atlas NetCDF specifique.
    atlas_base_dir : str, optional
        Repertoire parent des atlas (selection automatique).

    Returns
    -------
    float
        Hauteur en metres au-dessus du zero des cartes.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> hauteur_eau(44.667, -1.167,
    ...            datetime(2026, 3, 9, 7, 38, tzinfo=timezone.utc),
    ...            td4_file="Arcachon.td4")
    3.42
    """
    if td4_file is not None:
        m = Maree.from_td4(td4_file, lat=latitude)
    elif atlas_dir is not None:
        m = Maree.from_atlas(atlas_dir, lat=latitude, lon=longitude)
    elif atlas_base_dir is not None:
        m = Maree.from_atlas_auto(atlas_base_dir, lat=latitude, lon=longitude)
    else:
        raise ValueError("Fournir td4_file, atlas_dir ou atlas_base_dir")

    return m.hauteur(dateheure)


# ─────────────────────────────────────────────────────────────────────────────
# CLI / validation
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    td4_path = Path(__file__).parent / "Arcachon.td4"
    if not td4_path.exists():
        print(f"Fichier td4 non trouve : {td4_path}")
        sys.exit(1)

    m = Maree.from_td4(str(td4_path), lat=44.667)

    print(f"Port : {m.name}")
    print(f"Z0 = {m.z0:.4f} m")
    print(f"Constituants utide : {len(m._utide_names)}")
    print(f"Constituants extra : {len(m._extra_names)}")
    print(f"Ignores : {len(m._skipped)}")

    # Reference maree.info — Arcachon 9 mars 2026 (UTC+1)
    tz_paris = timezone(timedelta(hours=1))
    refs = [
        (datetime(2026, 3, 9, 2, 25, tzinfo=tz_paris), 0.95, "BM"),
        (datetime(2026, 3, 9, 8, 38, tzinfo=tz_paris), 3.67, "PM"),
        (datetime(2026, 3, 9, 14, 38, tzinfo=tz_paris), 1.16, "BM"),
        (datetime(2026, 3, 9, 20, 56, tzinfo=tz_paris), 3.56, "PM"),
    ]

    print(f"\n{'=' * 60}")
    print("  Validation — Arcachon 9 mars 2026 (ref: maree.info)")
    print(f"{'=' * 60}")
    print(f"  {'Type':>4s}  {'Heure':>6s}  {'Predit':>8s}  {'Ref':>8s}  {'Ecart':>8s}")
    for dt, ref, kind in refs:
        p = m.hauteur(dt)
        print(
            f"  {kind:>4s}  {dt.strftime('%Hh%M'):>6s}  {p:7.2f} m  {ref:7.2f} m  {p - ref:+7.2f} m"
        )

    print()
    from datetime import date

    m.maree_jour(date(2026, 3, 9), tz_offset_h=1)
