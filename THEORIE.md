# 🌊 Comprendre les marées — Astronomie et analyse harmonique

## Pourquoi la mer monte et descend ?

La marée est causée par l'**attraction gravitationnelle** de la Lune et du Soleil sur les masses d'eau terrestres. La force de marée dépend de la **masse** de l'astre et surtout de sa **distance** (en $1/d^3$) :

$$F_{\text{marée}} \propto \frac{M}{d^3}$$

| Astre | Masse (kg) | Distance (km) | Contribution marée |
|-------|:----------:|:--------------:|:------------------:|
| 🌙 Lune | 7.34 × 10²² | 384 400 | **100 %** (référence) |
| ☀️ Soleil | 1.99 × 10³⁰ | 149 600 000 | **46 %** |
| ♀ Vénus | 4.87 × 10²⁴ | ~41 000 000 (min) | 0.000 05 % |
| ♃ Jupiter | 1.90 × 10²⁷ | ~630 000 000 (min) | 0.000 01 % |

> **La Lune domine** malgré sa faible masse, car elle est 389 fois plus proche que le Soleil. Vénus et Jupiter ont un effet réel mais négligeable (~0.05 mm).

---

## Le bourrelet de marée : pourquoi deux fois par jour ?

La Terre ne subit pas une simple « attraction vers la Lune ». La force de marée crée **deux bourrelets** opposés :

```
                         🌙 Lune
                          ↓
            ┌─────────────────────────────┐
           ╱    Bourrelet côté Lune        ╲
      ~~~~╱  (attraction gravitationnelle)  ╲~~~~
     │   ╱                                   ╲   │
     │  │          🌍 Terre                    │  │    ← Pleine Mer
     │   ╲                                   ╱   │
      ~~~~╲   (force centrifuge/inertie)    ╱~~~~
           ╲    Bourrelet opposé           ╱
            └─────────────────────────────┘
                    Pleine Mer aussi !

     ↑                                         ↑
  Basse Mer                                 Basse Mer
  (sur les côtés)                          (sur les côtés)
```

- **Côté Lune** : l'eau est attirée plus fort que le centre de la Terre → bourrelet
- **Côté opposé** : le centre de la Terre est attiré plus fort que l'eau → l'eau « reste en arrière » → second bourrelet

La Terre tourne sur elle-même en **24h** sous ces deux bourrelets. Résultat : **2 pleines mers et 2 basses mers par jour**.

---

## Les périodes astronomiques fondamentales

Chaque mouvement astronomique a une période précise. Ce sont les « horloges » de la marée :

```
┌──────────────────────────────────────────────────────────────────────┐
│                    LES 6 HORLOGES DE LA MARÉE                        │
├───────┬──────────────────────────────┬───────────────┬───────────────┤
│ Sym.  │ Mouvement                    │ Période       │ Vitesse (°/h) │
├───────┼──────────────────────────────┼───────────────┼───────────────┤
│  τ    │ Jour lunaire moyen           │ 24h 50min 28s │  14.492 052   │
│  s    │ Mois tropique (Lune/Soleil)  │ 27.321 jours  │   0.549 017   │
│  h    │ Année tropique (Terre/Soleil)│ 365.242 jours │   0.041 069   │
│  p    │ Périgée lunaire              │ 8.847 ans     │   0.004 642   │
│  N'   │ Nœud lunaire (rétrograde)    │ 18.613 ans    │  -0.002 206   │
│  p₁   │ Périhélie terrestre          │ 20 940 ans    │   0.000 002   │
└───────┴──────────────────────────────┴───────────────┴───────────────┘
```

### Explication de chaque période

#### τ — Le jour lunaire (24h 50min)

```
         Midi jour 1              Midi jour 2
             ↓                        ↓
    ☀️       🌍 ─── 🌙         ☀️      🌍 ─────── 🌙
                                              ↗
                                    La Lune a avancé
                                    de ~13° en 24h

    ├──── 24h (jour solaire) ────┤
    ├──── 24h 50min (jour lunaire) ──────────┤
```

La Lune avance de **~13° par jour** sur son orbite. La Terre doit tourner 50 minutes de plus pour se retrouver face à la Lune. C'est pourquoi **la marée retarde de ~50 min chaque jour**.

#### s — Le mois lunaire (27.3 jours)

La Lune fait le tour de la Terre en 27.3 jours. Sa **déclinaison** (position nord/sud par rapport à l'équateur) varie au cours du mois, ce qui module l'amplitude des constituants diurnes.

```
        Vue de côté (plan orbital)

              ↑ Nord
    Lune max nord        Lune à l'équateur        Lune max sud
         🌙                                            🌙
        ╱                      🌙                       ╲
       ╱                       │                          ╲
  ────🌍──────────────────────🌍──────────────────────────🌍────
       ╲                       │                          ╱
        ╲                                                ╱
              ↓ Sud

  ├── ~7 jours ──┤── ~7 jours ──┤── ~7 jours ──┤── ~7 jours ──┤
  └──────────────── 27.3 jours (1 mois tropique) ─────────────┘
```

#### h — L'année tropique (365.25 jours)

La distance Terre-Soleil et la déclinaison du Soleil varient sur un an. Les marées d'équinoxe (mars, septembre) sont plus fortes : le Soleil est dans le plan de l'équateur, ses bourrelets s'ajoutent maximalement à ceux de la Lune.

#### p — Le périgée lunaire (8.85 ans)

L'orbite de la Lune est elliptique. Le point le plus proche (**périgée**) tourne lentement en 8.85 ans. Quand la pleine/nouvelle Lune coïncide avec le périgée → **supertide**.

```
              Orbite lunaire (exagérée)

                    Apogée (405 500 km)
                        🌙
                       ╱   ╲
                     ╱       ╲
          ─────── 🌍           ╲
                     ╲       ╱
                       ╲   ╱
                        🌙
                    Périgée (363 300 km)
                    ↑
                    Marée +15% plus forte !

        Le périgée tourne en 8.85 ans ──►
```

#### N' — La régression des nœuds lunaires (18.6 ans)

Le plan de l'orbite lunaire est incliné de 5° par rapport à l'écliptique. Les points d'intersection (**nœuds**) reculent lentement sur un cycle de 18.6 ans. Cela modifie la déclinaison maximale de la Lune (entre 18° et 28°) et donc l'amplitude des marées sur ~19 ans.

> C'est le fameux **cycle nodal** : les corrections $f$ et $u$ dans la formule de prédiction en tiennent compte.

#### p₁ — Le périhélie terrestre (20 940 ans)

Le point de l'orbite terrestre le plus proche du Soleil se déplace très lentement. Effet négligeable en pratique sur une vie humaine.

---

## Semi-diurne vs diurne : pourquoi ça dépend de l'endroit ?

```
  SEMI-DIURNE (2 PM + 2 BM / jour)         DIURNE (1 PM + 1 BM / jour)
  Atlantique, Manche, Mer du Nord            Golfe du Mexique, Mer de Chine

  7m ┤     ╭─╮          ╭─╮                 3m ┤          ╭────╮
     │    ╱   ╲        ╱   ╲                   │         ╱      ╲
  4m ┤   ╱     ╲      ╱     ╲                  │        ╱        ╲
     │  ╱       ╲    ╱       ╲               1m ┤───────╱          ╲───────
  1m ┤─╱         ╲──╱         ╲─                │
     └──┬──┬──┬──┬──┬──┬──┬──┬──               └──┬──┬──┬──┬──┬──┬──┬──┬──
      00  03  06  09  12  15  18  21             00  03  06  09  12  15  18  21

  Constituant dominant : M2                    Constituants dominants : K1, O1
  Période ≈ 12h 25min                          Période ≈ 24h — 25h
```

Le type de marée dépend de la **géométrie du bassin** (résonance) et de la **latitude** :
- Les constituants **semi-diurnes** (M2, S2) dominent là où le bassin résonne à ~12h
- Les constituants **diurnes** (K1, O1) dominent là où le bassin résonne à ~24h
- En France métropolitaine : marées **semi-diurnes** partout

---

## Vives-eaux et mortes-eaux : le rôle du Soleil

Le cycle vives-eaux / mortes-eaux dure **14.8 jours** (demi-mois synodique) :

```
  VIVES-EAUX (Nouvelle/Pleine Lune)        MORTES-EAUX (Quartiers)
  Bourrelets Lune + Soleil alignés          Bourrelets perpendiculaires

        ☀️                                        ☀️
        │                                         │
        │     ← Bourrelets alignés                │
        ↓                                         ↓
  ~~~~  🌍  ~~~~  🌙                         ~~~~  🌍  ~~~~
                                                   │
                                                   🌙
                                              (bourrelets croisés)

  Marnage maximal                           Marnage minimal
  M2 + S2 en phase                          M2 et S2 en opposition
  Coefficient ~100-120                      Coefficient ~20-45
```

C'est l'interférence entre **M2** (période 12h25) et **S2** (période 12h00) qui crée ce battement de 14.8 jours.

---

## Les constituants harmoniques principaux

Chaque constituant est une sinusoïde de période fixe. La marée réelle est leur **somme** :

$$h(t) = Z_0 + \sum_{i} f_i \cdot H_i \cdot \cos\!\Big(\omega_i \, t + V_i + u_i - G_i\Big)$$

### Constituants semi-diurnes (~12h) — 2 cycles par jour

| Nom | Période | Vitesse (°/h) | Origine | Amplitude typique |
|:---:|:-------:|:------------:|---------|:-----------------:|
| **M2** | 12h 25min 14s | 28.9841 | Lune, attraction principale | **~1 à 4 m** |
| **S2** | 12h 00min 00s | 30.0000 | Soleil, attraction principale | ~0.3 à 1.2 m |
| **N2** | 12h 39min 30s | 28.4397 | Lune, ellipticité orbitale | ~0.2 à 0.8 m |
| **K2** | 11h 58min 02s | 30.0821 | Soleil+Lune, déclinaison | ~0.1 à 0.3 m |
| L2 | 12h 11min 02s | 29.5285 | Lune, ellipticité | ~0.05 m |
| T2 | 12h 01min 05s | 29.9590 | Soleil, ellipticité orbitale | ~0.05 m |
| μ2 | 12h 52min 11s | 27.9682 | Lune, variation mensuelle | ~0.05 m |
| ν2 | 12h 37min 36s | 28.5126 | Lune, ellipticité | ~0.05 m |

### Constituants diurnes (~24h) — 1 cycle par jour

| Nom | Période | Vitesse (°/h) | Origine | Amplitude typique |
|:---:|:-------:|:------------:|---------|:-----------------:|
| **K1** | 23h 56min 04s | 15.0411 | Soleil+Lune, déclinaison | ~0.05 à 0.15 m |
| **O1** | 25h 49min 10s | 13.9430 | Lune, déclinaison | ~0.04 à 0.12 m |
| **P1** | 24h 03min 57s | 14.9589 | Soleil, déclinaison | ~0.02 à 0.05 m |
| Q1 | 26h 52min 06s | 13.3987 | Lune, ellipticité + déclinaison | ~0.01 m |
| J1 | 23h 05min 54s | 15.5854 | Lune, déclinaison | ~0.005 m |

### Constituants longue période — cycles de jours à années

| Nom | Période | Origine |
|:---:|:-------:|---------|
| **Mf** | 13.66 jours | Lune, déclinaison (demi-mois) |
| **Mm** | 27.55 jours | Lune, distance (mois anomalistique) |
| **Ssa** | 182.6 jours | Soleil, déclinaison (demi-année) |
| **Sa** | 365.25 jours | Soleil, distance (année) |

### Constituants de faible profondeur (shallow water) — harmoniques non-linéaires

En eau peu profonde (côtes, estuaires), les **non-linéarités** génèrent par friction et déformation des harmoniques de fréquences combinées :

| Nom | Période | Origine |
|:---:|:-------:|---------|
| **M4** | 6h 12min 37s | Harmonique 2 de M2 |
| **MS4** | 6h 05min 14s | Interaction M2 × S2 |
| **MN4** | 6h 16min 57s | Interaction M2 × N2 |
| **M6** | 4h 08min 25s | Harmonique 3 de M2 |

> À Arcachon par exemple, M4 atteint **0.22 m** — la distorsion du signal en eau peu profonde est très significative.

---

## Les nombres de Doodson

Chaque constituant est identifié par 6 nombres entiers $(n_1, n_2, n_3, n_4, n_5, n_6)$ qui donnent sa vitesse angulaire comme combinaison des 6 horloges astronomiques :

$$\omega = n_1 \cdot \tau + n_2 \cdot s + n_3 \cdot h + n_4 \cdot p + n_5 \cdot N' + n_6 \cdot p_1$$

```
Constituant   n₁  n₂  n₃  n₄  n₅  n₆    Vitesse (°/h)    Interprétation
─────────────────────────────────────────────────────────────────────────────
  Z0           0   0   0   0   0   0       0.000 000       Niveau moyen
  Mm           0   1   0  -1   0   0       0.544 375       Mois anomalistique
  Mf           0   2   0   0   0   0       1.098 033       2× mois tropique
  O1           1  -1   0   0   0   0      13.943 036       Lune diurne
  K1           1   1   0   0   0   0      15.041 069       Déclinaison diurne
  M2           2   0   0   0   0   0      28.984 104       Lune semi-diurne
  S2           2   2  -2   0   0   0      30.000 000       Soleil semi-diurne
  N2           2  -1   0   1   0   0      28.439 730       Ellipticité lunaire
  M4           4   0   0   0   0   0      57.968 208       M2 × 2 (shallow)
```

> Le nombre de Doodson est l'ADN du constituant : il encode exactement quel(s) phénomène(s) astronomique(s) le produisent.

---

## Synthèse : de l'astronomie à la courbe de marée

```
  Mouvements astronomiques          Constituants           Marée observée
  ═══════════════════════          ═════════════           ════════════════

  🌙 Lune tourne (27.3j) ──────►  M2 (12h25)  ──┐
  ☀️ Soleil (365.25j)    ──────►  S2 (12h00)  ──┤
  🌙 Orbite elliptique   ──────►  N2 (12h39)  ──┤
  🌙 Déclinaison lunaire ──────►  K1 (23h56)  ──┤       ╭──╮      ╭──╮
  ☀️ Déclinaison solaire ──────►  O1 (25h49)  ──┼──►   ╱    ╲    ╱    ╲
  🌙 Périgée (8.85 ans)  ──────►  corrections  ──┤    ╱      ╲──╱      ╲──
  🌙 Nœuds (18.6 ans)    ──────►  f, u nodaux ──┤
  🏖️ Bathymétrie locale  ──────►  M4, MS4...  ──┘    Courbe résultante
                                   (37+ ondes)         = somme de toutes
                                                        les sinusoïdes
```

### Exemple concret : Port-en-Bessin

Les 5 constituants les plus importants et leur contribution :

```
  Amplitude
  2.5m ┤  ██
       │  ██
  2.0m ┤  ██
       │  ██
  1.5m ┤  ██
       │  ██
  1.0m ┤  ██    ██
       │  ██    ██
  0.5m ┤  ██    ██    ██
       │  ██    ██    ██    ██
  0.0m ┤──██────██────██────██────██──
         M2    S2    N2    M4    K2

         2.32   0.79  0.43  0.22  0.21  mètres
```

M2 seul représente déjà **~70 %** du signal de marée. En ajoutant S2 et N2, on atteint **~90 %**. Les 34 autres constituants affinent le résultat.

---

## Références

- **Schureman, P.** (1958). *Manual of Harmonic Analysis and Prediction of Tides*. US Coast and Geodetic Survey.
- **Doodson, A.T.** (1921). *The Harmonic Development of the Tide-Generating Potential*. Proc. Royal Society A, 100(704).
- **Simon, B.** (2007). *La marée océanique côtière*. Institut Océanographique, Paris.
- **SHOM** — Service Hydrographique et Océanographique de la Marine. [shom.fr](https://www.shom.fr)
