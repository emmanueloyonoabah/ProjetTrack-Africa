# ProjetTrack Africa — Guide pas à pas

Application Streamlit de suivi de l'avancement physique, financier et temporel (courbe en S, jalons, EVM simplifié) de projets de génie civil.

## 1. Contenu du dossier

```
app.py                  Application complète
requirements.txt        Dépendances Python
.streamlit/config.toml  Thème clair (couleurs)
.gitignore              Exclut data/ (généré au lancement) et les fichiers temporaires
GUIDE.md                Ce guide
data/                   Créé automatiquement au premier lancement (CSV + config.json)
```

## 2. Lancer en local (Windows)

1. Installer Python 3.10 ou plus récent depuis python.org (cocher « Add Python to PATH »).
2. Ouvrir PowerShell dans le dossier du projet :

```powershell
cd "C:\Users\FAYA COMPUTER\Desktop\Projet 4 PJ"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

3. Le navigateur s'ouvre sur `http://localhost:8501`.

Si PowerShell refuse d'activer l'environnement : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis relancer l'activation.

### Comptes de démonstration

| Rôle | Identifiant | Mot de passe |
|---|---|---|
| Ingénieur Suivi / Planificateur | `planificateur` | `Suivi#2025` |
| Directeur de Projet / Encadrant | `directeur` | `Direction#2025` |

Au premier lancement, 12 semaines de données fictives sont chargées (Gros œuvre en retard et en surcoût) pour que les tableaux de bord soient immédiatement lisibles.

### Prise en main

- **Planificateur** : *Saisie hebdomadaire* → date du point, lot, avancement cumulé (%), dépenses de la semaine, observations → *Enregistrer*. L'auteur et l'horodatage sont ajoutés automatiquement. Une correction crée une nouvelle ligne et marque l'ancienne comme « Remplacée ».
- **Directeur** : *Tableau de bord*, *Courbe en S* (global ou par lot, physique / financier EVM / rythme hebdomadaire), *Alertes et dérives*, *Historique*, *Exports* (rapport de synthèse CSV), *Paramètres*.
- **Pour un projet réel** : *Paramètres → Données → Vider toutes les saisies*, puis renseigner dans *Paramètres* le nom du projet, la date de démarrage, la durée, les budgets et les semaines de début et de fin de chaque lot. Changer ensuite les mots de passe (*Paramètres → Utilisateurs*).

## 3. Règles de calcul

| Indicateur | Formule |
|---|---|
| Avancement prévu du lot | Courbe en S (lissage) entre la semaine de début et la semaine de fin |
| Avancement global | Moyenne des lots pondérée par leur budget |
| Écart d'avancement | Réel − Prévu (en points de %) |
| PV / EV / AC | Budget × % prévu / Budget × % réel / dépenses cumulées |
| SPI = EV / PV, CPI = EV / AC | Performance délai et coût |
| Taux de consommation | AC / Budget |
| Coût final estimé (EAC) | Budget / CPI |
| Fin estimée | Durée contractuelle / SPI(t), avec SPI(t) = semaine acquise / semaine courante (Earned Schedule, indicatif) |

Seuils par défaut (modifiables dans *Paramètres*) : retard mineur ≥ 2 pts, retard critique ≥ 5 pts, CPI < 0,95 attention, CPI < 0,85 critique.
Codes couleur : vert = conforme / en avance, orange = attention / retard mineur, rouge = retard critique / surcoût.

## 4. Pousser sur GitHub

1. Créer un compte sur github.com, puis un dépôt vide (*New repository*), par exemple `projettrack-africa`, sans README ni .gitignore.
2. Installer Git (git-scm.com), puis dans PowerShell, dans le dossier du projet :

```powershell
git init
git add .
git commit -m "ProjetTrack Africa - version initiale"
git branch -M main
git remote add origin https://github.com/<votre-compte>/projettrack-africa.git
git push -u origin main
```

Le fichier `.gitignore` empêche d'envoyer le dossier `data/` (comptes et saisies). Vérifier sur GitHub que `app.py`, `requirements.txt` et `.streamlit/config.toml` sont bien présents.

## 5. Déployer sur Streamlit Community Cloud

1. Aller sur share.streamlit.io et se connecter avec le compte GitHub.
2. Cliquer sur *Create app* → *Deploy a public app from GitHub*.
3. Renseigner : dépôt `<votre-compte>/projettrack-africa`, branche `main`, fichier principal `app.py`.
4. (Optionnel) *Advanced settings* → choisir la version de Python (3.11 ou 3.12 conseillée).
5. Cliquer sur *Deploy*. Après quelques minutes, l'application est en ligne sur une adresse `https://<nom>.streamlit.app`.

Chaque `git push` sur `main` redéploie automatiquement l'application.

### Limites importantes de l'hébergement gratuit

- **Les fichiers CSV ne sont pas persistants sur Streamlit Cloud.** Le disque est réinitialisé à chaque redémarrage ou redéploiement : les saisies faites en ligne sont alors perdues, et les données de démonstration sont régénérées. Pour une démonstration ou une soutenance, c'est suffisant. Pour un suivi réel, utiliser l'application en local (ou sur un serveur avec disque persistant) et exporter régulièrement le journal CSV depuis *Exports*.
- Les comptes de démonstration sont publics dans ce guide : changez les mots de passe avant toute mise en ligne accessible à des tiers. Le dépôt GitHub peut aussi être mis en privé (Streamlit Cloud sait déployer un dépôt privé).
- Pour une version multi-utilisateurs réellement persistante, remplacer les CSV par une base de données (par exemple Supabase ou Google Sheets via `st.connection`) : seules les fonctions de la section « Stockage CSV » de `app.py` sont à adapter.

## 6. Problèmes fréquents

| Symptôme | Solution |
|---|---|
| `streamlit` introuvable | Activer l'environnement virtuel, puis `pip install -r requirements.txt` |
| Erreur `width="stretch"` ou `position="hidden"` | Streamlit trop ancien : `pip install -U streamlit` (version 1.50 ou plus) |
| `localhost` ne répond pas | Essayer `http://127.0.0.1:8501` |
| Repartir de zéro en local | Fermer l'application, supprimer le dossier `data/`, relancer |
| Port déjà utilisé | `streamlit run app.py --server.port 8502` |
