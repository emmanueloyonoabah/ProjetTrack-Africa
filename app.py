"""
ProjetTrack Africa — suivi de l'avancement physique, financier et temporel
de projets de génie civil (courbes en S, jalons, Earned Value Management simplifié).

Stack : Streamlit · Pandas · NumPy · Plotly · stockage CSV local (dossier data/).
Lancement : streamlit run app.py
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ════════════════════════════════════════════════════════════════════
# 1. CONSTANTES
# ════════════════════════════════════════════════════════════════════
APP_NAME = "ProjetTrack Africa"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
USERS_CSV = DATA_DIR / "utilisateurs.csv"
LOTS_CSV = DATA_DIR / "lots.csv"
SUIVI_CSV = DATA_DIR / "suivi_hebdo.csv"
CONFIG_JSON = DATA_DIR / "config.json"

ROLE_PLANIF = "Ingénieur Suivi / Planificateur"
ROLE_DIR = "Directeur de Projet / Encadrant"
ROLES = [ROLE_PLANIF, ROLE_DIR]

LOT_TERRA = "Terrassement / Préparation de site"
LOT_GO = "Gros œuvre / Fondations & Structures"
LOT_SO = "Second œuvre / Finitions"
LOT_VRD = "VRD (Voiries et Réseaux Divers)"
LOTS = [LOT_TERRA, LOT_GO, LOT_SO, LOT_VRD]
LOT_COURT = {LOT_TERRA: "Terrassement", LOT_GO: "Gros œuvre", LOT_SO: "Second œuvre", LOT_VRD: "VRD"}

# Palette : neutres techniques + indicateurs sémantiques stricts
C = {
    "ok": "#1E8E5A",
    "warn": "#D98200",
    "bad": "#C62F2F",
    "neutral": "#6B7785",
    "ink": "#1F2933",
    "muted": "#8A94A0",
    "line": "#E3E7EB",
    "accent": "#2F5D8A",
}
SOFT = {"ok": "#E7F4EC", "warn": "#FDF1DC", "bad": "#FBE7E7", "neutral": "#EEF0F3"}
LEVEL_RANK = {"bad": 2, "warn": 1, "ok": 0, "neutral": 0}

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

DEFAULT_CONFIG = {
    "projet": "Complexe administratif régional — Phase 1",
    "client": "Direction Régionale des Infrastructures",
    "localisation": "Abidjan, Côte d'Ivoire",
    "date_debut": "",  # ISO, renseignée à l'initialisation
    "duree_semaines": 40,
    "taux_usd_fcfa": 600.0,
    "fuseau": "Africa/Abidjan",
    "seuil_retard_mineur": 2.0,  # points de % d'écart d'avancement
    "seuil_retard_critique": 5.0,
    "seuil_cpi_attention": 0.95,
    "seuil_cpi_critique": 0.85,
}

DEFAULT_LOTS = pd.DataFrame(
    {
        "lot": LOTS,
        "budget_fcfa": [180_000_000, 620_000_000, 280_000_000, 170_000_000],
        "semaine_debut": [1, 5, 20, 16],
        "semaine_fin": [8, 26, 36, 38],
    }
)

SUIVI_COLS = [
    "id", "date_point", "semaine", "lot", "avancement_pct",
    "depense_semaine_fcfa", "commentaire", "auteur", "role", "horodatage",
]

DEMO_USERS = [
    ("planificateur", "Suivi#2025", "Ing. Koffi Mensah", ROLE_PLANIF),
    ("directeur", "Direction#2025", "Dr. Aminata Diallo", ROLE_DIR),
]


# ════════════════════════════════════════════════════════════════════
# 2. FORMATAGE
# ════════════════════════════════════════════════════════════════════
def fr_num(x: float, d: int = 1) -> str:
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s.replace("-", "−")


def fmt_pct(x: float, d: int = 1) -> str:
    return f"{fr_num(x, d)} %"


def fmt_pts(x: float) -> str:
    sign = "+" if x > 0.049 else ""
    return f"{sign}{fr_num(x, 1)} pts"


def fr_date(d: date) -> str:
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def esc(s) -> str:
    return html.escape(str(s))


def pill(label: str, level: str) -> str:
    return f'<span class="pill pill-{level}">{esc(label)}</span>'


def hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# ════════════════════════════════════════════════════════════════════
# 3. STOCKAGE CSV
# ════════════════════════════════════════════════════════════════════
def _atomic_write(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, path)


def hash_pwd(pwd: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${h}"


def check_pwd(pwd: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_pwd(pwd, salt), stored)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def save_config(cfg: dict) -> None:
    CONFIG_JSON.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_JSON.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def load_lots() -> pd.DataFrame:
    df = pd.read_csv(LOTS_CSV)
    df["budget_fcfa"] = df["budget_fcfa"].astype(float)
    df["semaine_debut"] = df["semaine_debut"].astype(int)
    df["semaine_fin"] = df["semaine_fin"].astype(int)
    order = {l: i for i, l in enumerate(LOTS)}
    return df.sort_values("lot", key=lambda s: s.map(order)).reset_index(drop=True)


def load_users() -> pd.DataFrame:
    return pd.read_csv(USERS_CSV, dtype=str).fillna("")


def load_suivi() -> pd.DataFrame:
    df = pd.read_csv(SUIVI_CSV)
    for col in SUIVI_COLS:
        if col not in df.columns:
            df[col] = np.nan
    df["commentaire"] = df["commentaire"].fillna("").astype(str)
    for col in ("auteur", "role", "lot", "date_point", "horodatage"):
        df[col] = df[col].fillna("").astype(str)
    df["id"] = df["id"].astype(int)
    df["semaine"] = df["semaine"].astype(int)
    df["avancement_pct"] = df["avancement_pct"].astype(float)
    df["depense_semaine_fcfa"] = df["depense_semaine_fcfa"].astype(float)
    return df[SUIVI_COLS]


def save_suivi(df: pd.DataFrame) -> None:
    _atomic_write(df[SUIVI_COLS], SUIVI_CSV)


def now_local(cfg: dict) -> datetime:
    try:
        return datetime.now(ZoneInfo(cfg.get("fuseau", "Africa/Abidjan"))).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def init_storage() -> None:
    """Crée les fichiers de données au premier lancement (avec un jeu de démonstration)."""
    DATA_DIR.mkdir(exist_ok=True)
    first_run = not CONFIG_JSON.exists()
    if first_run:
        cfg = dict(DEFAULT_CONFIG)
        cfg["date_debut"] = (monday_of(date.today()) - timedelta(weeks=11)).isoformat()
        save_config(cfg)
    if not LOTS_CSV.exists():
        _atomic_write(DEFAULT_LOTS, LOTS_CSV)
    if not USERS_CSV.exists():
        users = pd.DataFrame(
            [{"identifiant": u, "mot_de_passe": hash_pwd(p), "nom": n, "role": r} for u, p, n, r in DEMO_USERS]
        )
        _atomic_write(users, USERS_CSV)
    if not SUIVI_CSV.exists():
        if first_run:
            save_suivi(generate_demo(load_config(), load_lots()))
        else:
            save_suivi(pd.DataFrame(columns=SUIVI_COLS))


# ════════════════════════════════════════════════════════════════════
# 4. MOTEUR DE CALCUL (planning, EVM simplifié)
# ════════════════════════════════════════════════════════════════════
def planned_curve(debut: int, fin: int, weeks: np.ndarray) -> np.ndarray:
    """Avancement cumulé prévisionnel (%) d'un lot : courbe en S (smoothstep) entre début et fin."""
    n = max(int(fin) - int(debut) + 1, 1)
    t = np.clip((np.asarray(weeks, dtype=float) - debut + 1) / n, 0.0, 1.0)
    return t * t * (3 - 2 * t) * 100.0


def active_reports(suivi: pd.DataFrame) -> pd.DataFrame:
    """Dernière saisie en vigueur pour chaque couple (lot, semaine)."""
    if suivi.empty:
        return suivi.copy()
    s = suivi.sort_values(["horodatage", "id"])
    return s.drop_duplicates(["lot", "semaine"], keep="last")


def week_start(cfg: dict, w: int) -> date:
    return date.fromisoformat(cfg["date_debut"]) + timedelta(weeks=int(w) - 1)


def week_end(cfg: dict, w: int) -> date:
    return week_start(cfg, w) + timedelta(days=6)


class Model:
    """Séries temporelles par lot et globales + indicateurs à la semaine courante."""

    def __init__(self, cfg: dict, lots: pd.DataFrame, suivi: pd.DataFrame):
        self.act = active_reports(suivi)
        self.cur = int(self.act["semaine"].max()) if len(self.act) else 0
        self.horizon = int(max(cfg["duree_semaines"], lots["semaine_fin"].max(), self.cur))
        self.weeks = np.arange(self.horizon + 1)
        self.bac = float(lots["budget_fcfa"].sum())
        self.budgets = dict(zip(lots["lot"], lots["budget_fcfa"]))
        self.per_lot: dict[str, pd.DataFrame] = {}

        for r in lots.itertuples(index=False):
            pv = planned_curve(r.semaine_debut, r.semaine_fin, self.weeks)
            a = self.act[self.act["lot"] == r.lot].set_index("semaine")
            ev = a["avancement_pct"].reindex(self.weeks).ffill().fillna(0.0).to_numpy(dtype=float)
            ac = a["depense_semaine_fcfa"].reindex(self.weeks).fillna(0.0).cumsum().to_numpy(dtype=float)
            d = pd.DataFrame({"semaine": self.weeks, "pv_pct": pv, "ev_pct": ev, "ac": ac})
            d["pv_amt"] = r.budget_fcfa * d["pv_pct"] / 100
            d["ev_amt"] = r.budget_fcfa * d["ev_pct"] / 100
            d.loc[d["semaine"] > self.cur, ["ev_pct", "ev_amt", "ac"]] = np.nan  # futur inconnu
            self.per_lot[r.lot] = d

        g = pd.DataFrame({"semaine": self.weeks})
        for col in ("pv_amt", "ev_amt", "ac"):
            g[col] = sum(d[col] for d in self.per_lot.values())
        g["pv_pct"] = g["pv_amt"] / self.bac * 100
        g["ev_pct"] = g["ev_amt"] / self.bac * 100
        self.glob = g
        self.rows, self.tot = snapshot(self, cfg, self.cur)  # listes de dicts (None = indicateur non défini)
        self.snap = pd.DataFrame(self.rows)


def status_planning(ecart: float, pv: float, ev: float, cfg: dict) -> tuple[str, str]:
    if ev >= 99.99:
        return "Terminé", "ok"
    if pv <= 0 and ev <= 0:
        return "À démarrer", "neutral"
    if ecart <= -cfg["seuil_retard_critique"]:
        return "Retard critique", "bad"
    if ecart <= -cfg["seuil_retard_mineur"]:
        return "Retard mineur", "warn"
    if ecart >= cfg["seuil_retard_mineur"]:
        return "En avance", "ok"
    return "Conforme", "ok"


def status_budget(cpi, ac: float, ev_amt: float, budget: float, cfg: dict) -> tuple[str, str]:
    if ac <= 0:
        return ("Conforme", "ok") if ev_amt > 0 else ("Non démarré", "neutral")
    if ac > budget:
        return "Budget dépassé", "bad"
    if cpi >= cfg["seuil_cpi_attention"]:
        return "Conforme", "ok"
    if cpi >= cfg["seuil_cpi_critique"]:
        return "Attention", "warn"
    return "Surcoût", "bad"


def _metrics_row(name: str, s: pd.Series, budget: float, bac: float, cfg: dict) -> dict:
    pv, ev = float(s["pv_pct"]), float(s["ev_pct"])
    pv_amt, ev_amt, ac = float(s["pv_amt"]), float(s["ev_amt"]), float(s["ac"])
    ecart = ev - pv
    spi = ev_amt / pv_amt if pv_amt > 0 else None
    cpi = ev_amt / ac if ac > 0 else None
    eac = budget / cpi if cpi else None
    pl, pl_lvl = status_planning(ecart, pv, ev, cfg)
    bl, bl_lvl = status_budget(cpi, ac, ev_amt, budget, cfg)
    return {
        "lot": name, "budget": budget, "poids": budget / bac * 100,
        "pv_pct": pv, "ev_pct": ev, "ecart": ecart,
        "pv_amt": pv_amt, "ev_amt": ev_amt, "ac": ac,
        "conso": ac / budget * 100 if budget else 0.0,
        "cv": ev_amt - ac, "sv": ev_amt - pv_amt, "spi": spi, "cpi": cpi, "eac": eac,
        "plan_label": pl, "plan_level": pl_lvl, "bud_label": bl, "bud_level": bl_lvl,
    }


def snapshot(m: Model, cfg: dict, week: int) -> tuple[list[dict], dict]:
    rows = [_metrics_row(lot, d.loc[week], m.budgets[lot], m.bac, cfg) for lot, d in m.per_lot.items()]
    total = _metrics_row("Projet (global)", m.glob.loc[week], m.bac, m.bac, cfg)
    return rows, total


def earned_schedule(m: Model) -> float | None:
    """Semaine 'acquise' : moment où le prévisionnel atteignait l'avancement réel actuel."""
    if m.cur == 0:
        return None
    pv = m.glob["pv_pct"].to_numpy()
    ev = float(m.glob.loc[m.cur, "ev_pct"])
    i = int(np.searchsorted(pv, ev - 1e-9, side="left"))
    if i <= 0:
        return 0.0
    if i >= len(pv):
        return float(m.weeks[-1])
    span = pv[i] - pv[i - 1]
    frac = (ev - pv[i - 1]) / span if span > 0 else 0.0
    return float(m.weeks[i - 1] + frac)


def forecast_end(m: Model, cfg: dict) -> dict | None:
    """Fin estimée par tendance (Earned Schedule : durée / SPI(t)). Indicatif."""
    es = earned_schedule(m)
    if es is None or es <= 0:
        return None
    spi_t = es / m.cur
    dur = cfg["duree_semaines"]
    est = dur / spi_t
    delay = est - dur
    return {"spi_t": spi_t, "duree_est": est, "retard_sem": delay, "date": week_end(cfg, 1) + timedelta(weeks=est - 1)}


def compute_jalons(m: Model, lots: pd.DataFrame, cfg: dict) -> list[dict]:
    out = []
    for r in lots.itertuples(index=False):
        d = m.per_lot[r.lot]
        reached = d.loc[d["ev_pct"] >= 99.99, "semaine"]
        wk = int(reached.min()) if len(reached) else None
        if wk is not None:
            st_lbl, lvl = "Atteint", "ok"
        elif m.cur >= r.semaine_fin:
            st_lbl, lvl = "En retard", "bad"
        else:
            st_lbl, lvl = "À venir", "neutral"
        out.append({"nom": f"Fin {LOT_COURT.get(r.lot, r.lot)}", "lot": r.lot, "semaine": int(r.semaine_fin),
                    "statut": st_lbl, "niveau": lvl, "reel": wk})
    reached = m.glob.loc[m.glob["ev_pct"] >= 99.99, "semaine"]
    wk = int(reached.min()) if len(reached) else None
    dur = int(cfg["duree_semaines"])
    st_lbl, lvl = ("Atteint", "ok") if wk else (("En retard", "bad") if m.cur >= dur else ("À venir", "neutral"))
    out.append({"nom": "Réception provisoire", "lot": None, "semaine": dur, "statut": st_lbl, "niveau": lvl, "reel": wk})
    for j in out:
        j["date"] = week_end(cfg, j["semaine"])
    return sorted(out, key=lambda j: j["semaine"])


def build_alerts(ctx: "Ctx") -> list[dict]:
    """Détection de dérives : planning, budget, jalons, données manquantes."""
    m, cfg = ctx.model, ctx.cfg
    if m.cur == 0:
        return []
    out: list[dict] = []

    def add(level, rubrique, cible, court, detail, action):
        out.append({"niveau": level, "rubrique": rubrique, "cible": cible,
                    "court": court, "detail": detail, "action": action})

    scopes = [("Projet global", m.tot)] + [(LOT_COURT[r["lot"]], r) for r in m.rows]
    for cible, r in scopes:
        is_global = cible == "Projet global"
        if r["plan_level"] in ("warn", "bad"):
            crit = r["plan_level"] == "bad"
            add(r["plan_level"], "Planning", cible,
                f"{r['plan_label']} {'global' if is_global else cible} ({fmt_pts(r['ecart'])})",
                f"Avancement réel {fmt_pct(r['ev_pct'])} contre {fmt_pct(r['pv_pct'])} prévu, soit {fmt_pts(r['ecart'])}"
                + (f" (SPI {fr_num(r['spi'], 2)})." if r["spi"] is not None else "."),
                "Construire un planning de rattrapage : renfort d'équipes et de matériel, travail en postes décalés, "
                "sécurisation des approvisionnements ; réunion de crise avec les sous-traitants."
                if crit else
                "Surveiller de près : vérifier approvisionnements, disponibilité du matériel et effectifs ; "
                "recaler le planning à 2 semaines.")
        if r["bud_level"] in ("warn", "bad"):
            crit = r["bud_level"] == "bad"
            cpi_txt = f"CPI {fr_num(r['cpi'], 2)}" if r["cpi"] is not None else "CPI n/d"
            add(r["bud_level"], "Budget", cible,
                (f"Vigilance coût {'global' if is_global else cible} ({cpi_txt})" if r["bud_label"] == "Attention"
                 else f"{r['bud_label']} {'global' if is_global else cible} ({cpi_txt})"),
                f"Dépensé {ctx.money(r['ac'])} pour une valeur acquise de {ctx.money(r['ev_amt'])} "
                f"(écart de coût {ctx.money(r['cv'], signed=True)}, consommation {fmt_pct(r['conso'])} du budget)."
                + (f" Estimation à terminaison : {ctx.money(r['eac'])} pour un budget de {ctx.money(r['budget'])}."
                   if r["eac"] else ""),
                "Analyser les écarts de métrés et de prix unitaires, geler les engagements non essentiels, "
                "réestimer le coût final et informer le maître d'ouvrage."
                if crit else
                "Contrôler les attachements et la facturation des sous-traitants ; vérifier les quantités mises en œuvre.")
    for j in compute_jalons(m, ctx.lots, cfg):
        if j["statut"] == "En retard":
            add("bad", "Jalon", j["nom"], f"Jalon manqué : {j['nom']}",
                f"Échéance prévue en S{j['semaine']} ({fr_date(j['date'])}) non atteinte à la semaine S{m.cur}.",
                "Notifier le retard sur le jalon contractuel, évaluer l'exposition aux pénalités et replanifier.")
    for r in m.rows:
        in_progress = 0 < r["pv_pct"] < 100 and r["ev_pct"] < 99.99
        reported = ((m.act["lot"] == r["lot"]) & (m.act["semaine"] == m.cur)).any()
        if in_progress and not reported:
            add("warn", "Données", LOT_COURT[r["lot"]], f"Saisie manquante : {LOT_COURT[r['lot']]} (S{m.cur})",
                f"Le lot est en cours selon le planning mais aucun point n'a été saisi pour la semaine S{m.cur}.",
                "Demander à l'ingénieur de suivi de saisir l'avancement et les dépenses du lot.")
    return sorted(out, key=lambda a: -LEVEL_RANK[a["niveau"]])


class Ctx:
    """Contexte de page : configuration, données, modèle de calcul et devise d'affichage."""

    def __init__(self):
        self.cfg = load_config()
        self.lots = load_lots()
        self.suivi = load_suivi()
        self.model = Model(self.cfg, self.lots, self.suivi)
        self.devise = st.session_state.get("devise") or "FCFA"
        self.rate = float(self.cfg["taux_usd_fcfa"])

    def cur_amt(self, x_fcfa):
        return x_fcfa if self.devise == "FCFA" else x_fcfa / self.rate

    def to_fcfa(self, x):
        return x if self.devise == "FCFA" else x * self.rate

    def money(self, x, signed: bool = False) -> str:
        if x is None or pd.isna(x):
            return "—"
        v = self.cur_amt(float(x))
        a = abs(v)
        if a >= 1e9:
            s = fr_num(v / 1e9, 2) + " Md"
        elif a >= 1e6:
            s = fr_num(v / 1e6, 1) + " M"
        else:
            s = fr_num(v, 0)
        if signed and v > 0:
            s = "+" + s
        return f"{s} {self.devise}"


# ════════════════════════════════════════════════════════════════════
# 5. DONNÉES DE DÉMONSTRATION
# ════════════════════════════════════════════════════════════════════
def generate_demo(cfg: dict, lots: pd.DataFrame, n_weeks: int = 12) -> pd.DataFrame:
    debut = date.fromisoformat(cfg["date_debut"])
    # (vitesse relative au prévisionnel, facteur de coût)
    profils = {LOT_TERRA: (1.10, 0.98), LOT_GO: (0.55, 1.32), LOT_SO: (1.0, 1.0), LOT_VRD: (0.9, 1.0)}
    notes = {
        (LOT_TERRA, 2): "Décapage et purge des zones molles terminés.",
        (LOT_TERRA, 5): "Remblai compacté — essais Proctor conformes.",
        (LOT_TERRA, 7): "Plateforme livrée en avance sur le planning.",
        (LOT_GO, 6): "Livraison des aciers HA retardée (port d'Abidjan).",
        (LOT_GO, 8): "Saison des pluies : 3 jours d'arrêt sur coulage des semelles.",
        (LOT_GO, 10): "Panne centrale à béton, location d'une centrale de secours (surcoût).",
        (LOT_GO, 12): "Renfort de 12 ferrailleurs en cours de mobilisation.",
    }
    auteur, role = DEMO_USERS[0][2], ROLE_PLANIF
    weeks = np.arange(0, n_weeks + 1)
    rows, rid = [], 1
    for r in lots.itertuples(index=False):
        speed, cost = profils.get(r.lot, (1.0, 1.0))
        pv = planned_curve(r.semaine_debut, r.semaine_fin, weeks)
        ev = np.maximum.accumulate(np.minimum(100.0, np.round(pv * speed * 2) / 2))
        ac = r.budget_fcfa * ev / 100 * cost
        spend = np.round(np.diff(ac, prepend=0.0) / 10_000) * 10_000
        for w in range(1, n_weeks + 1):
            if pv[w] <= 0 and ev[w] <= 0:
                continue
            if ev[w] >= 100 and ev[w - 1] >= 100:
                continue  # lot terminé : plus de saisie
            d_point = debut + timedelta(weeks=w - 1, days=4)
            rows.append({
                "id": rid, "date_point": d_point.isoformat(), "semaine": w, "lot": r.lot,
                "avancement_pct": float(ev[w]), "depense_semaine_fcfa": float(spend[w]),
                "commentaire": notes.get((r.lot, w), ""), "auteur": auteur, "role": role,
                "horodatage": datetime.combine(d_point, datetime.min.time()).replace(hour=17, minute=10 + rid % 40).isoformat(timespec="seconds"),
            })
            rid += 1
    return pd.DataFrame(rows, columns=SUIVI_COLS)


# ════════════════════════════════════════════════════════════════════
# 6. STYLE (CSS) ET COMPOSANTS HTML
# ════════════════════════════════════════════════════════════════════
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, .stApp, .stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp input, .stApp textarea, .stApp button, .stApp [data-baseweb] { font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] { font-family: 'Material Symbols Rounded' !important; }
.stApp { background: #F5F6F8; }
footer, [data-testid="stDecoration"], [data-testid="stToolbar"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1380px; }
section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E3E7EB; }
section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }

/* Cartes */
[class*="st-key-card-"] { background: #FFFFFF; border: 1px solid #E3E7EB !important; border-radius: 12px; box-shadow: 0 1px 2px rgba(31,41,51,.04); padding: .4rem .5rem .9rem .5rem; }
[data-testid="stForm"] { background: #FFFFFF; border: 1px solid #E3E7EB; border-radius: 12px; }
.card-title { font-size: .82rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: #6B7785; margin: .2rem 0 .4rem 0; }

/* En-tête de page */
.pt-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
.pt-eyebrow { font-size: .72rem; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: #2F5D8A; }
.pt-title { font-size: 1.75rem; font-weight: 700; color: #1F2933; line-height: 1.2; margin-top: .15rem; }
.pt-sub { color: #6B7785; font-size: .92rem; margin-top: .2rem; }
.chip { display: inline-block; background: #FFFFFF; border: 1px solid #E3E7EB; color: #3E4C59; border-radius: 999px; padding: .28rem .75rem; font-size: .8rem; font-weight: 500; margin-left: .4rem; white-space: nowrap; }

/* Bandeau d'alerte */
.banner { display: flex; gap: .9rem; align-items: flex-start; border-radius: 10px; padding: .85rem 1.1rem; margin: 0 0 1.1rem 0; border: 1px solid; border-left-width: 6px; }
.banner-bad { background: #FBE7E7; border-color: #E9B4B4; border-left-color: #C62F2F; color: #7A1B1B; }
.banner-warn { background: #FDF1DC; border-color: #EBCB93; border-left-color: #D98200; color: #704300; }
.banner-ok { background: #E7F4EC; border-color: #B5DCC5; border-left-color: #1E8E5A; color: #14573A; }
.banner-neutral { background: #EEF0F3; border-color: #D5DAE0; border-left-color: #6B7785; color: #3E4C59; }
.banner-tag { font-weight: 700; font-size: .78rem; letter-spacing: .08em; text-transform: uppercase; white-space: nowrap; padding-top: .1rem; }
.banner-body { font-size: .92rem; line-height: 1.45; }
.banner-body b { font-weight: 600; }

/* KPI */
.kpi { background: #FFFFFF; border: 1px solid #E3E7EB; border-top: 4px solid #C5CCD3; border-radius: 12px; padding: .9rem 1rem 1rem 1rem; min-height: 172px; box-shadow: 0 1px 2px rgba(31,41,51,.04); }
.kpi-ok { border-top-color: #1E8E5A; } .kpi-warn { border-top-color: #D98200; } .kpi-bad { border-top-color: #C62F2F; } .kpi-neutral { border-top-color: #C5CCD3; }
.kpi-label { font-size: .74rem; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: #6B7785; }
.kpi-value { font-size: 1.9rem; font-weight: 700; color: #1F2933; line-height: 1.25; margin-top: .25rem; font-variant-numeric: tabular-nums; }
.kpi-value.small { font-size: 1.45rem; padding: .3rem 0; }
.kpi-value.v-ok { color: #1E8E5A; } .kpi-value.v-warn { color: #B96F00; } .kpi-value.v-bad { color: #C62F2F; }
.kpi-sub { font-size: .82rem; color: #6B7785; margin-top: .3rem; line-height: 1.5; }

/* Pastilles de statut */
.pill { display: inline-block; border-radius: 999px; padding: .12rem .6rem; font-size: .74rem; font-weight: 600; white-space: nowrap; }
.pill-ok { background: #E7F4EC; color: #14683F; } .pill-warn { background: #FDF1DC; color: #8A5200; }
.pill-bad { background: #FBE7E7; color: #A32323; } .pill-neutral { background: #EEF0F3; color: #52606D; }

/* Tableaux HTML */
.tbl-wrap { overflow-x: auto; }
table.tbl { width: 100%; border-collapse: collapse; font-size: .86rem; }
table.tbl th { text-align: left; font-size: .72rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: #6B7785; padding: .55rem .6rem; border-bottom: 1px solid #E3E7EB; white-space: nowrap; }
table.tbl td { padding: .65rem .6rem; border-bottom: 1px solid #EEF0F3; color: #1F2933; vertical-align: middle; }
table.tbl tr:last-child td { border-bottom: none; }
table.tbl tr.total td { font-weight: 600; background: #F8F9FB; }
table.tbl td.num, table.tbl th.num { text-align: right; font-variant-numeric: tabular-nums; }
.bar { position: relative; height: 8px; background: #E9ECEF; border-radius: 4px; min-width: 110px; }
.bar-fill { height: 100%; border-radius: 4px; }
.bar-plan { position: absolute; top: -4px; width: 2px; height: 16px; background: #1F2933; border-radius: 1px; }
.neg { color: #C62F2F; font-weight: 600; } .pos { color: #1E8E5A; font-weight: 600; }

/* Alertes détaillées */
.alert-card { background: #FFFFFF; border: 1px solid #E3E7EB; border-left: 6px solid #C5CCD3; border-radius: 10px; padding: .8rem 1rem; margin-bottom: .7rem; }
.alert-card.a-bad { border-left-color: #C62F2F; } .alert-card.a-warn { border-left-color: #D98200; }
.alert-top { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; margin-bottom: .25rem; }
.alert-title { font-weight: 600; color: #1F2933; }
.alert-detail { color: #3E4C59; font-size: .88rem; }
.alert-action { color: #52606D; font-size: .84rem; margin-top: .35rem; }

/* Clé/valeur */
.kv { display: flex; justify-content: space-between; gap: 1rem; padding: .5rem 0; border-bottom: 1px solid #EEF0F3; font-size: .9rem; }
.kv:last-child { border-bottom: none; } .kv span:first-child { color: #6B7785; } .kv span:last-child { font-weight: 600; color: #1F2933; text-align: right; }

/* Connexion */
.login-brand { text-align: center; margin: 3.5rem 0 1.2rem 0; }
.logo-mark { display: inline-flex; align-items: center; justify-content: center; width: 52px; height: 52px; border-radius: 12px; background: #1F2933; color: #FFFFFF; font-weight: 700; font-size: 1.15rem; letter-spacing: .02em; margin-bottom: .8rem; }
.login-brand h1 { font-size: 1.6rem; margin: 0; color: #1F2933; }
.login-brand p { color: #6B7785; margin: .3rem 0 0 0; font-size: .92rem; }
.side-user { background: #F5F6F8; border: 1px solid #E3E7EB; border-radius: 10px; padding: .7rem .8rem; margin-bottom: .6rem; }
.side-user b { display: block; color: #1F2933; } .side-user span { color: #6B7785; font-size: .8rem; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background: #2F5D8A; border-color: #2F5D8A; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def card(key: str):
    return st.container(border=True, key=f"card-{key}")


def card_title(text: str) -> None:
    st.markdown(f'<div class="card-title">{esc(text)}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str, level: str = "neutral", colored: bool = True, small: bool = False) -> str:
    vcls = f" v-{level}" if colored and level in ("ok", "warn", "bad") else ""
    vcls += " small" if small else ""
    return (f'<div class="kpi kpi-{level}"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value{vcls}">{value}</div><div class="kpi-sub">{sub}</div></div>')


def render_banner(ctx: Ctx) -> None:
    m = ctx.model
    if m.cur == 0:
        st.markdown('<div class="banner banner-neutral"><div class="banner-tag">Information</div>'
                    '<div class="banner-body">Aucun point de situation n\'a encore été saisi. '
                    'Les indicateurs apparaîtront dès la première saisie hebdomadaire.</div></div>',
                    unsafe_allow_html=True)
        return
    alerts = [a for a in build_alerts(ctx) if a["rubrique"] != "Données"]
    bad = [a for a in alerts if a["niveau"] == "bad"]
    warn = [a for a in alerts if a["niveau"] == "warn"]
    if bad:
        lvl, tag = "bad", "Alerte critique"
        items = [a["court"] for a in bad]
    elif warn:
        lvl, tag = "warn", "Attention"
        items = [a["court"] for a in warn]
    else:
        st.markdown(f'<div class="banner banner-ok"><div class="banner-tag">Conforme</div><div class="banner-body">'
                    f'Aucune dérive détectée à la semaine S{m.cur} : planning et budget dans les tolérances.</div></div>',
                    unsafe_allow_html=True)
        return
    shown = items[:3]
    more = f" · <b>+{len(items) - 3} autre(s)</b>" if len(items) > 3 else ""
    body = " · ".join(f"<b>{esc(s)}</b>" for s in shown) + more
    extra = f" ({len(bad)} critique(s), {len(warn)} à surveiller)" if bad and warn else ""
    st.markdown(f'<div class="banner banner-{lvl}"><div class="banner-tag">{tag}</div>'
                f'<div class="banner-body">Semaine S{m.cur}{extra} — {body}</div></div>', unsafe_allow_html=True)


def page_header(ctx: Ctx, title: str, subtitle: str, banner: bool = True) -> None:
    cfg, m = ctx.cfg, ctx.model
    chips = f'<span class="chip">{esc(cfg["projet"])}</span>'
    if m.cur > 0:
        chips += (f'<span class="chip">Point de situation S{m.cur} / {cfg["duree_semaines"]} · '
                  f'{fr_date(week_end(cfg, m.cur))}</span>')
    st.markdown(f'<div class="pt-head"><div><div class="pt-eyebrow">{APP_NAME}</div>'
                f'<div class="pt-title">{esc(title)}</div><div class="pt-sub">{esc(subtitle)}</div></div>'
                f'<div>{chips}</div></div>', unsafe_allow_html=True)
    if banner:
        render_banner(ctx)


# ════════════════════════════════════════════════════════════════════
# 7. GRAPHIQUES PLOTLY
# ════════════════════════════════════════════════════════════════════
PLOT_CFG = {"displayModeBar": False}


def style_fig(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=12, t=64, b=8),
        font=dict(family="Inter, sans-serif", size=13, color=C["ink"]),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.09, x=0, bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=C["line"]),
    )
    fig.update_xaxes(showline=True, linecolor=C["line"], gridcolor="#EEF0F3", zeroline=False)
    fig.update_yaxes(showline=False, gridcolor="#EEF0F3", zeroline=False)
    return fig


def _week_axis(fig: go.Figure, horizon: int) -> None:
    fig.update_xaxes(range=[0, horizon], dtick=4 if horizon > 20 else 2, tickprefix="S", title=None)


def scope_data(ctx: Ctx, scope: str):
    m = ctx.model
    if scope == "Projet global":
        return m.glob, m.tot, m.bac
    row = next(r for r in m.rows if r["lot"] == scope)
    return m.per_lot[scope], row, m.budgets[scope]


def fig_scurve(ctx: Ctx, scope: str = "Projet global", height: int = 440) -> go.Figure:
    m, cfg = ctx.model, ctx.cfg
    d, r, _ = scope_data(ctx, scope)
    col = C[r["plan_level"]] if r["plan_level"] in ("ok", "warn", "bad") else C["accent"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["semaine"], y=d["pv_pct"], name="Prévisionnel", mode="lines",
                             line=dict(color=C["muted"], width=2.5, dash="dash"), hovertemplate="%{y:.1f} %"))
    if m.cur > 0:
        dd = d[d["semaine"] <= m.cur]
        fig.add_trace(go.Scatter(x=dd["semaine"], y=dd["pv_pct"], mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=dd["semaine"], y=dd["ev_pct"], name="Réel cumulé", mode="lines+markers",
                                 line=dict(color=col, width=3.5), marker=dict(size=6, color=col),
                                 fill="tonexty", fillcolor=hex_rgba(col, 0.13), hovertemplate="%{y:.1f} %"))
        fig.add_vline(x=m.cur, line_dash="dot", line_color=C["accent"], opacity=0.55)
        fig.add_annotation(x=m.cur, y=1, yref="paper", text=f"Point de situation S{m.cur}", showarrow=False,
                           yanchor="bottom", font=dict(size=11, color=C["accent"]))
        fig.add_annotation(x=m.cur, y=float(d.loc[m.cur, "ev_pct"]), text=f"<b>{fmt_pts(r['ecart'])}</b>",
                           showarrow=True, arrowhead=0, arrowcolor=col, ax=-46, ay=-34,
                           font=dict(size=12, color=col), bgcolor="white", bordercolor=col, borderwidth=1, borderpad=3)
    jalons = compute_jalons(m, ctx.lots, cfg)
    if scope != "Projet global":
        jalons = [j for j in jalons if j["lot"] == scope]
    jx = [j["semaine"] for j in jalons]
    jy = [float(d.loc[x, "pv_pct"]) for x in jx]
    fig.add_trace(go.Scatter(
        x=jx, y=jy, name="Jalons", mode="markers+text" if scope != "Projet global" else "markers",
        text=[j["nom"] for j in jalons], textposition="bottom right", textfont=dict(size=10, color=C["neutral"]),
        marker=dict(symbol="diamond", size=12, line=dict(color="white", width=1.5),
                    color=[C[j["niveau"]] if j["niveau"] != "neutral" else C["neutral"] for j in jalons]),
        customdata=[[j["statut"]] for j in jalons], hovertemplate="%{text} — %{customdata[0]}<extra></extra>"))
    _week_axis(fig, m.horizon)
    fig.update_yaxes(range=[0, 108], ticksuffix=" %", title="Avancement cumulé")
    return style_fig(fig, height)


def fig_evm(ctx: Ctx, scope: str = "Projet global", height: int = 440) -> go.Figure:
    m = ctx.model
    d, r, budget = scope_data(ctx, scope)
    col = C[r["bud_level"]] if r["bud_level"] in ("ok", "warn", "bad") else C["accent"]
    unit = "M " + ctx.devise
    f = lambda s: ctx.cur_amt(s) / 1e6
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["semaine"], y=f(d["pv_amt"]), name="Valeur prévue (PV)", mode="lines",
                             line=dict(color=C["muted"], width=2.5, dash="dash"), hovertemplate="%{y:,.1f} " + unit))
    if m.cur > 0:
        dd = d[d["semaine"] <= m.cur]
        fig.add_trace(go.Scatter(x=dd["semaine"], y=f(dd["ev_amt"]), name="Valeur acquise (EV)", mode="lines+markers",
                                 line=dict(color=C["accent"], width=3), marker=dict(size=5), hovertemplate="%{y:,.1f} " + unit))
        fig.add_trace(go.Scatter(x=dd["semaine"], y=f(dd["ac"]), name="Coût réel (AC)", mode="lines+markers",
                                 line=dict(color=col, width=3), marker=dict(size=5), hovertemplate="%{y:,.1f} " + unit))
        fig.add_vline(x=m.cur, line_dash="dot", line_color=C["accent"], opacity=0.55)
    fig.add_hline(y=f(budget), line_dash="dot", line_color=C["ink"], opacity=0.35,
                  annotation_text=f"Budget {ctx.money(budget)}", annotation_position="top left",
                  annotation_font=dict(size=11, color=C["neutral"]))
    _week_axis(fig, m.horizon)
    fig.update_yaxes(title=f"Montant cumulé ({unit})", rangemode="tozero")
    return style_fig(fig, height)


def fig_weekly(ctx: Ctx, height: int = 420) -> go.Figure:
    m = ctx.model
    g = m.glob
    inc_pv = g["pv_pct"].diff().fillna(0)
    inc_ev = g["ev_pct"].diff()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=g["semaine"][1:], y=inc_pv[1:], name="Prévu", marker_color="#C5CCD3", hovertemplate="%{y:.2f} pts"))
    fig.add_trace(go.Bar(x=g["semaine"][1:m.cur + 1], y=inc_ev[1:m.cur + 1], name="Réel", marker_color=C["accent"],
                         hovertemplate="%{y:.2f} pts"))
    fig.update_layout(barmode="group", bargap=0.25)
    _week_axis(fig, m.horizon)
    fig.update_yaxes(title="Avancement de la semaine (pts du projet)", ticksuffix=" pts")
    return style_fig(fig, height)


def fig_lots(ctx: Ctx, height: int = 340) -> go.Figure:
    s = ctx.model.snap
    names = [LOT_COURT[l] for l in s["lot"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=names, x=s["pv_pct"], orientation="h", name="Prévu", marker_color="#C5CCD3",
                         text=[fmt_pct(v) for v in s["pv_pct"]], textposition="outside", cliponaxis=False))
    fig.add_trace(go.Bar(y=names, x=s["ev_pct"], orientation="h", name="Réel",
                         marker_color=[C[l] if l in ("ok", "warn", "bad") else C["accent"] for l in s["plan_level"]],
                         text=[fmt_pct(v) for v in s["ev_pct"]], textposition="outside", cliponaxis=False))
    fig.update_layout(barmode="group", bargap=0.35, hovermode="closest", showlegend=False, margin=dict(l=8, r=12, t=16, b=8))
    fig.update_xaxes(range=[0, 118], ticksuffix=" %", title=None)
    fig.update_yaxes(autorange="reversed")
    return style_fig(fig, height)


# ════════════════════════════════════════════════════════════════════
# 8. AUTHENTIFICATION
# ════════════════════════════════════════════════════════════════════
def page_login() -> None:
    inject_css()
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(f'<div class="login-brand"><div class="logo-mark">PT</div><h1>{APP_NAME}</h1>'
                    '<p>Pilotage de l\'avancement physique, financier et temporel des chantiers de génie civil</p></div>',
                    unsafe_allow_html=True)
        with st.form("login", border=True):
            user = st.text_input("Identifiant", placeholder="ex. directeur")
            pwd = st.text_input("Mot de passe", type="password")
            ok = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if ok:
            users = load_users()
            row = users[users["identifiant"].str.lower() == user.strip().lower()]
            if len(row) == 1 and check_pwd(pwd, row.iloc[0]["mot_de_passe"]):
                r = row.iloc[0]
                st.session_state.update(auth=True, user=r["identifiant"], name=r["nom"], role=r["role"])
                st.rerun()
            else:
                time.sleep(0.7)
                st.error("Identifiant ou mot de passe incorrect.")
        with st.expander("Comptes de démonstration"):
            st.markdown(
                "| Rôle | Identifiant | Mot de passe |\n|---|---|---|\n"
                + "\n".join(f"| {r} | `{u}` | `{p}` |" for u, p, _, r in DEMO_USERS)
            )
            st.caption("À modifier avant toute utilisation réelle (page Paramètres → Utilisateurs).")


def sidebar_panel(ctx: Ctx) -> None:
    with st.sidebar:
        st.markdown(f'<div class="side-user"><b>{esc(st.session_state["name"])}</b>'
                    f'<span>{esc(st.session_state["role"])}</span></div>', unsafe_allow_html=True)
        st.segmented_control("Devise d'affichage", ["FCFA", "USD"], default="FCFA", key="devise",
                             help=f"Taux utilisé : 1 USD = {fr_num(ctx.rate, 0)} FCFA (modifiable dans Paramètres).")
        if st.button("Se déconnecter", icon=":material/logout:", width="stretch"):
            for k in ("auth", "user", "name", "role"):
                st.session_state.pop(k, None)
            st.rerun()


# ════════════════════════════════════════════════════════════════════
# 9. PAGES
# ════════════════════════════════════════════════════════════════════
def lots_table_html(ctx: Ctx) -> str:
    t = ctx.model.tot

    def row(r, total=False):
        ev_col = C[r["plan_level"]] if r["plan_level"] in ("ok", "warn", "bad") else C["accent"]
        ec = r["ecart"]
        ecart_cls = "neg" if ec <= -ctx.cfg["seuil_retard_mineur"] else ("pos" if ec >= ctx.cfg["seuil_retard_mineur"] else "")
        cpi = fr_num(r["cpi"], 2) if r["cpi"] is not None else "—"
        return (f'<tr class="{"total" if total else ""}"><td>{esc(r["lot"])}</td><td class="num">{ctx.money(r["budget"])}</td>'
                f'<td class="num">{fmt_pct(r["pv_pct"])}</td>'
                f'<td><div class="bar"><div class="bar-fill" style="width:{min(r["ev_pct"], 100):.1f}%;background:{ev_col}"></div>'
                f'<div class="bar-plan" style="left:calc({min(r["pv_pct"], 100):.1f}% - 1px)"></div></div></td>'
                f'<td class="num">{fmt_pct(r["ev_pct"])}</td><td class="num {ecart_cls}">{fmt_pts(ec)}</td>'
                f'<td>{pill(r["plan_label"], r["plan_level"])}</td>'
                f'<td class="num">{ctx.money(r["ac"])}</td><td class="num">{fmt_pct(r["conso"])}</td>'
                f'<td class="num">{cpi}</td><td>{pill(r["bud_label"], r["bud_level"])}</td></tr>')

    head = ("<tr><th>Lot d'ouvrage</th><th class='num'>Budget</th><th class='num'>Prévu</th><th>Avancement réel</th>"
            "<th class='num'>Réel</th><th class='num'>Écart</th><th>Planning</th><th class='num'>Dépensé</th>"
            "<th class='num'>Conso.</th><th class='num'>CPI</th><th>Budget</th></tr>")
    body = "".join(row(r) for r in ctx.model.rows) + row(t, total=True)
    return f'<div class="tbl-wrap"><table class="tbl">{head}{body}</table></div>'


def jalons_table_html(ctx: Ctx) -> str:
    rows = ""
    for j in compute_jalons(ctx.model, ctx.lots, ctx.cfg):
        reel = f"S{j['reel']}" if j["reel"] else "—"
        rows += (f"<tr><td>◆ {esc(j['nom'])}</td><td class='num'>S{j['semaine']}</td><td class='num'>{fr_date(j['date'])}</td>"
                 f"<td class='num'>{reel}</td><td>{pill(j['statut'], j['niveau'])}</td></tr>")
    head = "<tr><th>Jalon</th><th class='num'>Semaine prévue</th><th class='num'>Date prévue</th><th class='num'>Atteint en</th><th>Statut</th></tr>"
    return f'<div class="tbl-wrap"><table class="tbl">{head}{rows}</table></div>'


def empty_state(ctx: Ctx) -> bool:
    if ctx.model.cur == 0:
        st.info("Aucune donnée de suivi pour le moment. Rendez-vous sur **Saisie hebdomadaire** pour enregistrer le premier point de situation.",
                icon=":material/info:")
        return True
    return False


def page_dashboard() -> None:
    ctx = Ctx()
    page_header(ctx, "Tableau de bord", "Synthèse de l'avancement physique, financier et du planning")
    if empty_state(ctx):
        return
    m, cfg, t = ctx.model, ctx.cfg, ctx.model.tot
    fc = forecast_end(m, cfg)

    cols = st.columns(5, gap="small")
    cols[0].markdown(kpi("Avancement physique", fmt_pct(t["ev_pct"]),
                         f"Prévu : <b>{fmt_pct(t['pv_pct'])}</b><br>Semaine S{m.cur} sur {cfg['duree_semaines']}", "neutral", False),
                     unsafe_allow_html=True)
    cols[1].markdown(kpi("Écart d'avancement", fmt_pts(t["ecart"]),
                         f"{pill(t['plan_label'], t['plan_level'])}<br>SPI : <b>{fr_num(t['spi'], 2) if t['spi'] is not None else '—'}</b>",
                         t["plan_level"]), unsafe_allow_html=True)
    cols[2].markdown(kpi("Consommation du budget", fmt_pct(t["conso"]),
                         f"{ctx.money(t['ac'])} sur {ctx.money(t['budget'])}<br>{pill(t['bud_label'], t['bud_level'])}",
                         t["bud_level"]), unsafe_allow_html=True)
    cpi_txt = fr_num(t["cpi"], 2) if t["cpi"] is not None else "—"
    eac_txt = (f"Coût final estimé : <b>{ctx.money(t['eac'])}</b>" if t["eac"] else "Coût final estimé : —")
    cols[3].markdown(kpi("Performance coût (CPI)", cpi_txt,
                         f"Écart de coût : <b>{ctx.money(t['cv'], signed=True)}</b><br>{eac_txt}", t["bud_level"]),
                     unsafe_allow_html=True)
    if fc:
        lvl = "ok" if fc["retard_sem"] <= 1 else ("warn" if fc["retard_sem"] <= 4 else "bad")
        sign = "+" if fc["retard_sem"] > 0.05 else ""
        cols[4].markdown(kpi("Fin estimée (tendance)", fr_date(fc["date"]),
                             f"Contractuelle : {fr_date(week_end(cfg, cfg['duree_semaines']))}<br>"
                             f"Écart : <b>{sign}{fr_num(fc['retard_sem'], 1)} sem.</b>", lvl, False, small=True),
                         unsafe_allow_html=True)
    else:
        cols[4].markdown(kpi("Fin estimée (tendance)", "—", "Données insuffisantes", "neutral"), unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([5, 4], gap="medium")
    with left, card("scurve-mini"):
        card_title("Courbe en S — avancement cumulé du projet")
        st.plotly_chart(fig_scurve(ctx, height=360), width="stretch", config=PLOT_CFG)
    with right, card("lots-bar"):
        card_title("Avancement par lot · prévu vs réel")
        st.plotly_chart(fig_lots(ctx, height=360), width="stretch", config=PLOT_CFG)
        st.caption("Gris : prévu · Couleur : réel selon le statut du lot.")

    st.write("")
    with card("lots-table"):
        card_title("État des lots d'ouvrage")
        st.markdown(lots_table_html(ctx), unsafe_allow_html=True)
        st.caption("Le trait noir sur la barre indique l'avancement prévisionnel à la semaine courante ; "
                   "la barre colorée indique l'avancement réel.")
    st.write("")
    with card("jalons"):
        card_title("Jalons du projet")
        st.markdown(jalons_table_html(ctx), unsafe_allow_html=True)


def page_scurve() -> None:
    ctx = Ctx()
    page_header(ctx, "Courbe en S comparative", "Prévisionnel contre réel — physique, financier (EVM) et rythme hebdomadaire")
    if empty_state(ctx):
        return
    scope = st.selectbox("Périmètre d'analyse", ["Projet global"] + LOTS,
                         format_func=lambda x: x if x == "Projet global" else LOT_COURT[x])
    d, r, budget = scope_data(ctx, scope)
    c = st.columns(4)
    c[0].markdown(kpi("Réel / Prévu", f"{fmt_pct(r['ev_pct'])} / {fmt_pct(r['pv_pct'])}", pill(r["plan_label"], r["plan_level"]), r["plan_level"], False), unsafe_allow_html=True)
    c[1].markdown(kpi("Écart de planning", fmt_pts(r["ecart"]), f"SPI : {fr_num(r['spi'], 2) if r['spi'] is not None else '—'}", r["plan_level"]), unsafe_allow_html=True)
    c[2].markdown(kpi("Valeur acquise (EV)", ctx.money(r["ev_amt"]), f"Prévue (PV) : {ctx.money(r['pv_amt'])}", "neutral", False), unsafe_allow_html=True)
    c[3].markdown(kpi("Coût réel (AC)", ctx.money(r["ac"]), f"CPI : {fr_num(r['cpi'], 2) if r['cpi'] is not None else '—'} · {pill(r['bud_label'], r['bud_level'])}", r["bud_level"], False), unsafe_allow_html=True)
    st.write("")
    with card("scurve-main"):
        tabs = st.tabs(["Avancement physique (courbe en S)", "Financier (EVM)", "Rythme hebdomadaire"])
        with tabs[0]:
            st.plotly_chart(fig_scurve(ctx, scope), width="stretch", config=PLOT_CFG)
            st.caption("Zone teintée = écart entre le réel et le prévisionnel. Losanges = jalons de fin de lot "
                       "(vert : atteint, rouge : en retard, gris : à venir).")
        with tabs[1]:
            st.plotly_chart(fig_evm(ctx, scope), width="stretch", config=PLOT_CFG)
            st.caption("EV (valeur acquise) = budget × avancement réel ; PV = budget × avancement prévu ; AC = dépenses cumulées. "
                       "AC au-dessus de EV signale un surcoût ; EV sous PV signale un retard.")
        with tabs[2]:
            st.plotly_chart(fig_weekly(ctx), width="stretch", config=PLOT_CFG)
            st.caption("Gain d'avancement du projet, semaine par semaine, comparé au rythme prévu (périmètre global).")
    st.write("")
    with card("jalons2"):
        card_title("Jalons")
        st.markdown(jalons_table_html(ctx), unsafe_allow_html=True)


def page_alertes() -> None:
    ctx = Ctx()
    page_header(ctx, "Alertes et dérives", "Détection automatique des écarts de planning, de coût et de jalons", banner=False)
    if empty_state(ctx):
        return
    alerts = build_alerts(ctx)
    th = ctx.cfg
    st.caption(f"Seuils actifs — retard mineur : {fr_num(th['seuil_retard_mineur'], 1)} pts · retard critique : "
               f"{fr_num(th['seuil_retard_critique'], 1)} pts · CPI attention < {fr_num(th['seuil_cpi_attention'], 2)} · "
               f"CPI critique < {fr_num(th['seuil_cpi_critique'], 2)}")
    if not alerts:
        st.success("Aucune dérive détectée : planning et budget sont dans les tolérances.", icon=":material/check_circle:")
        return
    nb_bad = sum(a["niveau"] == "bad" for a in alerts)
    c = st.columns(3)
    c[0].markdown(kpi("Alertes critiques", str(nb_bad), "Action immédiate requise", "bad" if nb_bad else "ok"), unsafe_allow_html=True)
    c[1].markdown(kpi("À surveiller", str(len(alerts) - nb_bad), "Vigilance", "warn" if len(alerts) - nb_bad else "ok"), unsafe_allow_html=True)
    c[2].markdown(kpi("Semaine analysée", f"S{ctx.model.cur}", fr_date(week_end(ctx.cfg, ctx.model.cur)), "neutral", False), unsafe_allow_html=True)
    st.write("")
    for a in alerts:
        lvl_lbl = "Critique" if a["niveau"] == "bad" else "Attention"
        st.markdown(
            f'<div class="alert-card a-{a["niveau"]}"><div class="alert-top">{pill(lvl_lbl, a["niveau"])}'
            f'{pill(a["rubrique"], "neutral")}<span class="alert-title">{esc(a["court"])}</span></div>'
            f'<div class="alert-detail">{esc(a["detail"])}</div>'
            f'<div class="alert-action"><b>Action suggérée :</b> {esc(a["action"])}</div></div>',
            unsafe_allow_html=True)


def page_saisie() -> None:
    ctx = Ctx()
    cfg, m = ctx.cfg, ctx.model
    page_header(ctx, "Saisie hebdomadaire", "Point de situation de chantier par lot d'ouvrage")
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash, icon=":material/check_circle:")
    debut = date.fromisoformat(cfg["date_debut"])

    left, right = st.columns([3, 2], gap="large")
    with left:
        with card("saisie-ctx"):
            card_title("1 · Point de situation")
            c1, c2 = st.columns(2)
            d_point = c1.date_input("Date du point de situation", value=date.today(), format="DD/MM/YYYY", key="sx_date")
            lot = c2.selectbox("Lot d'ouvrage", LOTS, key="sx_lot")
            semaine = (d_point - debut).days // 7 + 1
            if semaine < 1:
                st.error(f"Cette date précède le démarrage du projet ({fr_date(debut)}).")
                return
            st.markdown(pill(f"Semaine S{semaine} · du {fr_date(week_start(cfg, semaine))} au {fr_date(week_end(cfg, semaine))}", "neutral"),
                        unsafe_allow_html=True)

        lrow = ctx.lots[ctx.lots["lot"] == lot].iloc[0]
        pv_now = float(planned_curve(lrow.semaine_debut, lrow.semaine_fin, np.array([semaine]))[0])
        a = m.act[m.act["lot"] == lot]
        prev = a[a["semaine"] < semaine].sort_values("semaine").tail(1)
        nxt = a[a["semaine"] > semaine].sort_values("semaine").head(1)
        same = a[a["semaine"] == semaine]
        prev_av = float(prev["avancement_pct"].iloc[0]) if len(prev) else 0.0
        max_av = float(nxt["avancement_pct"].iloc[0]) if len(nxt) else 100.0
        dep_cum_before = float(a.loc[a["semaine"] < semaine, "depense_semaine_fcfa"].sum())

        if len(same):
            s0 = same.iloc[0]
            st.info(f"Une saisie existe déjà pour ce lot en S{semaine} (par {s0['auteur']}, le {datetime.fromisoformat(s0['horodatage']).strftime('%d/%m/%Y à %H:%M')}). "
                    "Votre enregistrement la remplacera ; l'ancienne version reste visible dans l'historique.",
                    icon=":material/info:")
        step = 100_000.0 if ctx.devise == "FCFA" else 1_000.0
        default_av = float(same["avancement_pct"].iloc[0]) if len(same) else prev_av
        default_dep = float(ctx.cur_amt(same["depense_semaine_fcfa"].iloc[0])) if len(same) else 0.0
        default_com = same["commentaire"].iloc[0] if len(same) else ""
        with st.form("form_saisie"):
            card_title("2 · Avancement et dépenses")
            av = st.number_input("Avancement physique réel constaté — cumulé (%)", 0.0, 100.0, value=default_av,
                                 step=0.5, format="%.1f", key=f"sx_av_{lot}_{semaine}",
                                 help="Pourcentage cumulé d'exécution du lot depuis le démarrage.")
            dep = st.number_input(f"Dépenses réalisées sur la semaine ({ctx.devise})", min_value=0.0, value=default_dep,
                                  step=step, format="%.0f", key=f"sx_dep_{lot}_{semaine}_{ctx.devise}",
                                  help="Montant consommé sur le budget du lot pendant la semaine (le cumul est calculé automatiquement).")
            com = st.text_area("Observations de chantier (aléas, météo, approvisionnements, effectifs…)", value=default_com,
                               max_chars=400, key=f"sx_com_{lot}_{semaine}")
            ok = st.form_submit_button("Enregistrer le point de situation", type="primary", icon=":material/save:")
        if ok:
            if av < prev_av - 1e-9:
                st.error(f"L'avancement cumulé ne peut pas diminuer : {fmt_pct(prev_av)} déjà déclaré pour une semaine antérieure.")
            elif av > max_av + 1e-9:
                st.error(f"L'avancement dépasse celui déjà saisi pour une semaine ultérieure ({fmt_pct(max_av)}).")
            else:
                now = now_local(cfg)
                suivi = ctx.suivi
                new = {
                    "id": int(suivi["id"].max()) + 1 if len(suivi) else 1, "date_point": d_point.isoformat(),
                    "semaine": int(semaine), "lot": lot, "avancement_pct": float(av),
                    "depense_semaine_fcfa": round(ctx.to_fcfa(dep)), "commentaire": com.strip(),
                    "auteur": st.session_state["name"], "role": st.session_state["role"],
                    "horodatage": now.isoformat(timespec="seconds"),
                }
                save_suivi(pd.concat([suivi, pd.DataFrame([new])], ignore_index=True))
                st.session_state["flash"] = (f"Point enregistré : {LOT_COURT[lot]} · S{semaine} · {fmt_pct(av)} "
                                             f"— par {new['auteur']} le {now.strftime('%d/%m/%Y à %H:%M')}.")
                st.rerun()

    with right:
        with card("saisie-info"):
            card_title(f"Repères — {LOT_COURT[lot]}")
            prev_txt = f"{fmt_pct(prev_av)} (S{int(prev['semaine'].iloc[0])})" if len(prev) else "aucun"
            st.markdown(
                f'<div class="kv"><span>Avancement prévu en S{semaine}</span><span>{fmt_pct(pv_now)}</span></div>'
                f'<div class="kv"><span>Dernier avancement déclaré</span><span>{prev_txt}</span></div>'
                f'<div class="kv"><span>Écart prévu − dernier déclaré</span><span>{fmt_pts(pv_now - prev_av)}</span></div>'
                f'<div class="kv"><span>Budget du lot</span><span>{ctx.money(lrow.budget_fcfa)}</span></div>'
                f'<div class="kv"><span>Dépensé avant cette semaine</span><span>{ctx.money(dep_cum_before)}</span></div>'
                f'<div class="kv"><span>Fenêtre planifiée du lot</span><span>S{lrow.semaine_debut} → S{lrow.semaine_fin}</span></div>',
                unsafe_allow_html=True)
        st.write("")
        with card("saisie-mine"):
            card_title("Mes dernières saisies")
            mine = ctx.suivi[ctx.suivi["auteur"] == st.session_state["name"]].sort_values(["horodatage", "id"], ascending=False).head(6)
            if mine.empty:
                st.caption("Aucune saisie enregistrée avec ce compte.")
            else:
                v = pd.DataFrame({"Sem.": "S" + mine["semaine"].astype(str), "Lot": mine["lot"].map(LOT_COURT),
                                  "Avanc.": mine["avancement_pct"].map(lambda x: fmt_pct(x)),
                                  "Enregistré": mine["horodatage"].str.replace("T", " ").str[:16]})
                st.dataframe(v, hide_index=True, width="stretch")


def journal_df(ctx: Ctx) -> pd.DataFrame:
    s = ctx.suivi.sort_values(["horodatage", "id"]).copy()
    s["actif"] = ~s.duplicated(["lot", "semaine"], keep="last")
    return s.sort_values(["horodatage", "id"], ascending=False)


def page_historique() -> None:
    ctx = Ctx()
    page_header(ctx, "Historique des rapports", "Synthèse hebdomadaire et journal de traçabilité des saisies")
    if empty_state(ctx):
        return
    m, cfg = ctx.model, ctx.cfg
    tab1, tab2 = st.tabs(["Synthèse hebdomadaire", "Journal des saisies"])
    with tab1:
        g = m.glob[(m.glob["semaine"] >= 1) & (m.glob["semaine"] <= m.cur)].copy()
        spend_w = g["ac"].diff().fillna(g["ac"])
        nb = m.act.groupby("semaine").size().reindex(g["semaine"]).fillna(0).astype(int).to_numpy()
        rows = []
        for (_, r), sw, n in zip(g.iterrows(), spend_w, nb):
            lbl, _ = status_planning(r["ev_pct"] - r["pv_pct"], r["pv_pct"], r["ev_pct"], cfg)
            rows.append({"Semaine": f"S{int(r['semaine'])}", "Période": f"{fr_date(week_start(cfg, int(r['semaine'])))} → {fr_date(week_end(cfg, int(r['semaine'])))}",
                         "Prévu (%)": round(r["pv_pct"], 1), "Réel (%)": round(r["ev_pct"], 1),
                         "Écart (pts)": round(r["ev_pct"] - r["pv_pct"], 1), "Statut planning": lbl,
                         f"Dépenses de la semaine ({ctx.devise})": round(ctx.cur_amt(sw)),
                         f"Cumul dépensé ({ctx.devise})": round(ctx.cur_amt(r["ac"])), "Lots saisis": int(n)})
        df = pd.DataFrame(rows).iloc[::-1]
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "Prévu (%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
            "Réel (%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
            f"Dépenses de la semaine ({ctx.devise})": st.column_config.NumberColumn(format="localized"),
            f"Cumul dépensé ({ctx.devise})": st.column_config.NumberColumn(format="localized")})
    with tab2:
        j = journal_df(ctx)
        f1, f2, f3 = st.columns(3)
        lots_sel = f1.multiselect("Lot", LOTS, format_func=lambda x: LOT_COURT[x])
        auteurs = f2.multiselect("Auteur", sorted(j["auteur"].unique()))
        hide_old = f3.toggle("Masquer les versions remplacées", value=False)
        if lots_sel:
            j = j[j["lot"].isin(lots_sel)]
        if auteurs:
            j = j[j["auteur"].isin(auteurs)]
        if hide_old:
            j = j[j["actif"]]
        view = pd.DataFrame({
            "Statut": np.where(j["actif"], "En vigueur", "Remplacée"), "Semaine": "S" + j["semaine"].astype(str),
            "Date du point": pd.to_datetime(j["date_point"]).dt.strftime("%d/%m/%Y"), "Lot": j["lot"].map(LOT_COURT),
            "Avancement (%)": j["avancement_pct"], f"Dépense ({ctx.devise})": ctx.cur_amt(j["depense_semaine_fcfa"]).round(0),
            "Observations": j["commentaire"], "Auteur": j["auteur"], "Horodatage": j["horodatage"].str.replace("T", " "),
        })
        st.dataframe(view, hide_index=True, width="stretch", column_config={
            "Avancement (%)": st.column_config.NumberColumn(format="%.1f"),
            f"Dépense ({ctx.devise})": st.column_config.NumberColumn(format="localized")})
        st.caption(f"{len(view)} ligne(s). Chaque enregistrement conserve son auteur et son horodatage automatique ; "
                   "une correction crée une nouvelle ligne et marque l'ancienne comme remplacée.")


def _csv_safe(s: pd.Series) -> pd.Series:
    """Neutralise l'injection de formules à l'ouverture dans Excel."""
    return s.map(lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return ("﻿" + df.to_csv(sep=";", decimal=",", index=False)).encode("utf-8")


def synthese_report(ctx: Ctx, week: int) -> pd.DataFrame:
    snap, tot = snapshot(ctx.model, ctx.cfg, week)
    cfg = ctx.cfg
    rows = []
    for r in [*snap, tot]:
        rows.append({
            "Projet": cfg["projet"], "Semaine": f"S{week}", "Début de semaine": week_start(cfg, week).strftime("%d/%m/%Y"),
            "Lot": r["lot"], "Budget (FCFA)": round(r["budget"]), "Poids budget (%)": round(r["poids"], 1),
            "Avancement prévu (%)": round(r["pv_pct"], 1), "Avancement réel (%)": round(r["ev_pct"], 1),
            "Écart d'avancement (pts)": round(r["ecart"], 1), "Statut planning": r["plan_label"],
            "Valeur prévue PV (FCFA)": round(r["pv_amt"]), "Valeur acquise EV (FCFA)": round(r["ev_amt"]),
            "Coût réel AC (FCFA)": round(r["ac"]), "Taux de consommation (%)": round(r["conso"], 1),
            "Écart de coût CV (FCFA)": round(r["cv"]), "Écart de délai SV (FCFA)": round(r["sv"]),
            "SPI": round(r["spi"], 2) if r["spi"] is not None else "", "CPI": round(r["cpi"], 2) if r["cpi"] is not None else "",
            "Estimation à terminaison EAC (FCFA)": round(r["eac"]) if r["eac"] else "", "Statut budget": r["bud_label"],
        })
    return pd.DataFrame(rows)


def page_export() -> None:
    ctx = Ctx()
    page_header(ctx, "Exports", "Rapport de synthèse de chantier et journal complet au format CSV")
    if empty_state(ctx):
        return
    m = ctx.model
    weeks = sorted(m.act["semaine"].unique().tolist(), reverse=True)
    with card("export-synth"):
        card_title("Rapport de synthèse de chantier")
        week = st.selectbox("Semaine du rapport", weeks, format_func=lambda w: f"S{w} — {fr_date(week_end(ctx.cfg, w))}")
        rep = synthese_report(ctx, int(week))
        st.dataframe(rep, hide_index=True, width="stretch")
        fname = f"rapport_synthese_chantier_S{int(week):02d}.csv"
        st.download_button("Télécharger le rapport de synthèse (CSV)", to_csv_bytes(rep), file_name=fname,
                           mime="text/csv", type="primary", icon=":material/download:")
        st.caption("Montants exportés en FCFA, séparateur « ; » et décimale « , » (ouverture directe dans Excel en version française).")
    st.write("")
    with card("export-journal"):
        card_title("Journal complet des saisies")
        j = journal_df(ctx)
        out = pd.DataFrame({
            "Statut": np.where(j["actif"], "En vigueur", "Remplacée"), "Semaine": j["semaine"], "Date du point": j["date_point"],
            "Lot": j["lot"], "Avancement (%)": j["avancement_pct"], "Dépense semaine (FCFA)": j["depense_semaine_fcfa"].round(0),
            "Observations": _csv_safe(j["commentaire"]), "Auteur": _csv_safe(j["auteur"]), "Rôle": j["role"], "Horodatage": j["horodatage"],
        })
        st.download_button("Télécharger le journal des saisies (CSV)", to_csv_bytes(out), file_name="journal_saisies_chantier.csv",
                           mime="text/csv", icon=":material/download:")


def page_parametres() -> None:
    ctx = Ctx()
    page_header(ctx, "Paramètres", "Projet, seuils d'alerte, lots, utilisateurs et données", banner=False)
    cfg = ctx.cfg
    t1, t2, t3, t4 = st.tabs(["Projet et seuils", "Lots d'ouvrage", "Utilisateurs", "Données"])
    with t1:
        with st.form("f_cfg"):
            c1, c2 = st.columns(2)
            projet = c1.text_input("Nom du projet", cfg["projet"])
            client = c2.text_input("Maître d'ouvrage", cfg["client"])
            loc = c1.text_input("Localisation", cfg["localisation"])
            debut = c2.date_input("Date de démarrage (semaine 1)", date.fromisoformat(cfg["date_debut"]), format="DD/MM/YYYY")
            duree = c1.number_input("Durée contractuelle (semaines)", 4, 260, int(cfg["duree_semaines"]))
            taux = c2.number_input("Taux de change (1 USD = … FCFA)", 100.0, 2000.0, float(cfg["taux_usd_fcfa"]), step=5.0)
            st.markdown("**Seuils d'alerte**")
            s1, s2, s3, s4 = st.columns(4)
            rm = s1.number_input("Retard mineur (pts)", 0.5, 20.0, float(cfg["seuil_retard_mineur"]), step=0.5)
            rc = s2.number_input("Retard critique (pts)", 1.0, 40.0, float(cfg["seuil_retard_critique"]), step=0.5)
            ca = s3.number_input("CPI attention <", 0.5, 1.2, float(cfg["seuil_cpi_attention"]), step=0.01)
            cc = s4.number_input("CPI critique <", 0.3, 1.1, float(cfg["seuil_cpi_critique"]), step=0.01)
            if st.form_submit_button("Enregistrer", type="primary", icon=":material/save:"):
                if rc <= rm or cc >= ca:
                    st.error("Le seuil critique doit être plus sévère que le seuil d'attention (retard critique > retard mineur ; CPI critique < CPI attention).")
                else:
                    cfg.update(projet=projet.strip() or cfg["projet"], client=client.strip(), localisation=loc.strip(),
                               date_debut=debut.isoformat(), duree_semaines=int(duree), taux_usd_fcfa=float(taux),
                               seuil_retard_mineur=rm, seuil_retard_critique=rc, seuil_cpi_attention=ca, seuil_cpi_critique=cc)
                    save_config(cfg)
                    st.session_state["flash_p"] = "Paramètres enregistrés."
                    st.rerun()
        if st.session_state.get("flash_p"):
            st.success(st.session_state.pop("flash_p"), icon=":material/check_circle:")
    with t2:
        st.caption("Budget alloué et fenêtre planifiée de chaque lot : ils pilotent la courbe en S prévisionnelle.")
        ed = ctx.lots.rename(columns={"lot": "Lot", "budget_fcfa": "Budget (FCFA)", "semaine_debut": "Début (semaine)", "semaine_fin": "Fin (semaine)"})
        out = st.data_editor(ed, hide_index=True, width="stretch", disabled=["Lot"], key="ed_lots", column_config={
            "Budget (FCFA)": st.column_config.NumberColumn(min_value=1, step=1_000_000, format="%d"),
            "Début (semaine)": st.column_config.NumberColumn(min_value=1, step=1, format="%d"),
            "Fin (semaine)": st.column_config.NumberColumn(min_value=1, step=1, format="%d")})
        if st.button("Enregistrer les lots", type="primary", icon=":material/save:"):
            if out.isna().any().any() or (out["Fin (semaine)"] < out["Début (semaine)"]).any() or (out["Budget (FCFA)"] <= 0).any():
                st.error("Vérifiez les valeurs : budgets positifs, valeurs renseignées et fin ≥ début.")
            else:
                new = out.rename(columns={"Lot": "lot", "Budget (FCFA)": "budget_fcfa", "Début (semaine)": "semaine_debut", "Fin (semaine)": "semaine_fin"})
                _atomic_write(new, LOTS_CSV)
                st.success("Lots mis à jour.", icon=":material/check_circle:")
                st.rerun()
    with t3:
        users = load_users()
        st.dataframe(users[["identifiant", "nom", "role"]].rename(columns={"identifiant": "Identifiant", "nom": "Nom", "role": "Rôle"}),
                     hide_index=True, width="stretch")
        with st.form("f_user", clear_on_submit=True):
            st.markdown("**Ajouter ou réinitialiser un utilisateur**")
            u1, u2 = st.columns(2)
            ident = u1.text_input("Identifiant")
            nom = u2.text_input("Nom complet")
            role = u1.selectbox("Rôle", ROLES)
            pwd = u2.text_input("Mot de passe (8 caractères minimum)", type="password")
            if st.form_submit_button("Enregistrer l'utilisateur", icon=":material/person_add:"):
                ident = ident.strip()
                if not ident or not nom.strip() or len(pwd) < 8:
                    st.error("Identifiant, nom et mot de passe (8 caractères minimum) sont obligatoires.")
                else:
                    users = users[users["identifiant"].str.lower() != ident.lower()]
                    users = pd.concat([users, pd.DataFrame([{"identifiant": ident, "mot_de_passe": hash_pwd(pwd), "nom": nom.strip(), "role": role}])], ignore_index=True)
                    _atomic_write(users, USERS_CSV)
                    st.success(f"Utilisateur « {ident} » enregistré.", icon=":material/check_circle:")
                    st.rerun()
    with t4:
        st.markdown(f"**{len(ctx.suivi)}** ligne(s) de suivi enregistrée(s).")
        c1, c2 = st.columns(2)
        with c1, card("data-demo"):
            card_title("Jeu de démonstration")
            st.caption("Remplace toutes les saisies par 12 semaines de données fictives (Gros œuvre en retard et en surcoût).")
            ok1 = st.checkbox("Je confirme le remplacement des saisies actuelles", key="ck_demo")
            if st.button("Charger les données de démonstration", disabled=not ok1):
                save_suivi(generate_demo(cfg, ctx.lots))
                st.session_state.pop("ck_demo", None)
                st.rerun()
        with c2, card("data-clear"):
            card_title("Démarrer un projet réel")
            st.caption("Supprime toutes les saisies de suivi (action irréversible). Pensez à exporter le journal avant.")
            ok2 = st.checkbox("Je confirme la suppression de toutes les saisies", key="ck_clear")
            if st.button("Vider toutes les saisies", disabled=not ok2):
                save_suivi(pd.DataFrame(columns=SUIVI_COLS))
                st.session_state.pop("ck_clear", None)
                st.rerun()


# ════════════════════════════════════════════════════════════════════
# 10. POINT D'ENTRÉE
# ════════════════════════════════════════════════════════════════════
def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon=":material/engineering:", layout="wide",
                       initial_sidebar_state="expanded")
    init_storage()
    if not st.session_state.get("auth"):
        st.navigation([st.Page(page_login, title="Connexion", icon=":material/lock:")], position="hidden").run()
        return
    inject_css()
    P = lambda fn, title, icon, path, **kw: st.Page(fn, title=title, icon=f":material/{icon}:", url_path=path, **kw)
    saisie = P(page_saisie, "Saisie hebdomadaire", "edit_note", "saisie")
    histo = P(page_historique, "Historique", "history", "historique")
    if st.session_state["role"] == ROLE_DIR:
        pages = [
            P(page_dashboard, "Tableau de bord", "dashboard", "tableau-de-bord", default=True),
            P(page_scurve, "Courbe en S", "show_chart", "courbe-en-s"),
            P(page_alertes, "Alertes et dérives", "notification_important", "alertes"),
            saisie, histo,
            P(page_export, "Exports", "download", "exports"),
            P(page_parametres, "Paramètres", "settings", "parametres"),
        ]
    else:
        pages = [P(page_saisie, "Saisie hebdomadaire", "edit_note", "saisie", default=True), histo]
    pg = st.navigation(pages)
    sidebar_panel(Ctx())
    pg.run()


if __name__ == "__main__":
    main()
