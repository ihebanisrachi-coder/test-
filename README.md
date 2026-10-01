# Vnish pour Home Assistant

Intégration personnalisée (HACS) pour piloter un mineur Antminer équipé du firmware **Vnish**
depuis Home Assistant, via l'API locale du mineur (aucun cloud). Elle expose des entités
utilisables directement dans les automatisations : couper/relancer le minage, changer de
preset (donc de puissance), redémarrer, et surveiller hashrate, consommation et températures.

## Installation

**Avec HACS** : *HACS → ⋮ → Dépôts personnalisés* → ajouter ce dépôt (catégorie *Intégration*),
installer « Vnish », redémarrer Home Assistant.

**À la main** : copier `custom_components/vnish/` dans le dossier `custom_components/` de votre
configuration Home Assistant, puis redémarrer.

Ensuite : *Paramètres → Appareils et services → Ajouter une intégration → Vnish*, saisir l'adresse IP
du mineur et le mot de passe de son interface web (par défaut sous Vnish : `admin`).
Prérequis : Home Assistant 2025.1 ou plus récent (testé avec 2026.2), mineur joignable depuis Home Assistant
(port 80 pour l'API, port 4028 pour le hashrate).

## Entités

| Entité | Rôle |
|---|---|
| `switch.<mineur>_mining` | Arrête (`mining/stop`) / relance (`mining/resume`, puis `mining/start` si refusé) le minage |
| `select.<mineur>_preset` | Preset d'autotune actif, donc la puissance. Les noms valides sont les options du sélecteur ; leur libellé (« 3250 watt ~ 110 TH ») est dans les attributs |
| `select.<mineur>_active_pool` | Pool principal : options `1`, `2`, `3` (l'URL de chaque numéro est dans les attributs, jamais les identifiants). Les numéros suivent l'ordre des pools à l'installation et ne bougent pas quand le mineur réordonne sa liste ; les autres pools restent en secours |
| `button.<mineur>_use_pool_N` | Un bouton par pool configuré (N = 1, 2, 3) : l'appuyer le place en tête, comme le sélecteur |
| `button.<mineur>_reboot` | Redémarre le mineur |
| `button.<mineur>_restart_mining` | Relance uniquement le minage |
| `sensor.<mineur>_state` | État Vnish (`mining`, `stopped`, `failure`…) |
| `sensor.<mineur>_hashrate` | TH/s (commande RPC `summary`, `GHS 5s`) |
| `sensor.<mineur>_power` | Consommation en W |
| `sensor.<mineur>_efficiency` | J/TH, calculé |
| `sensor.<mineur>_chip_temperature` / `_pcb_temperature` | Température max des puces / cartes |
| `sensor.<mineur>_fan_N` | Vitesse de chaque ventilateur (tr/min) |

`<mineur>` est le nom d'hôte du mineur. Les données sont relevées toutes les 30 s.

Choisir un pool le place en tête de la liste du mineur ; pour en ajouter un, configurez-le d'abord dans l'interface Vnish. Changer de preset ou de pool relance le minage si le mineur le demande (`restart_required`) ; l'intégration relit
ensuite le réglage pour confirmer qu'il a été pris en compte, et signale une erreur sinon.

## Automatisations

Exemples prêts à adapter dans [`examples/automations.yaml`](examples/automations.yaml) :
pause aux heures pleines, preset suivant le surplus solaire, protection surchauffe,
alerte mineur hors ligne ou ventilateur à l'arrêt. Dans le YAML, appelez simplement les actions
habituelles, par exemple :

```yaml
actions:
  - action: select.select_option
    target: {entity_id: select.antminer_s19_preset}
    data: {option: "2000"}
```

## À valider sur votre mineur

Cette intégration a été écrite et testée **sans mineur Vnish sous la main** : les tests utilisent un
faux mineur qui reproduit l'API telle que la décrivent d'autres clients Vnish. L'authentification
(`POST /api/v1/unlock`), les commandes (`mining/*`, `system/reboot`, `settings`,
`autotune/presets`) et la commande RPC viennent de ce code de référence ; en revanche les **noms de
champs de `/summary`** (températures, ventilateurs, puissance) varient peut-être selon la version du
firmware. Une valeur introuvable donne simplement une entité « inconnue », jamais une erreur.

Pour vérifier, lancez la sonde (lecture seule, bibliothèque standard uniquement) depuis n'importe
quelle machine du réseau :

```bash
python3 tools/vnish_probe.py 192.168.1.50 --password admin > probe.json
```

Elle enregistre les réponses de `info`, `summary`, `settings`, `autotune/presets`, `perf-summary` et du
RPC (mots de passe et identifiants de pool masqués, adresse MAC tronquée ; relisez avant de partager).
La documentation de l'API de votre version est aussi servie par le mineur à `http://<ip>/docs`.

## Dépannage

- **« Impossible de joindre le mineur »** : mauvaise IP, ou le mineur ne tourne pas sous Vnish.
- **« Mot de passe incorrect »** : c'est le mot de passe de l'interface web Vnish. En cas de
  changement ultérieur, Home Assistant propose de se ré-authentifier.
- **Pas de hashrate** : le port RPC 4028 n'est pas joignable ; les autres entités fonctionnent.
- **Journaux détaillés** : `logger: logs: custom_components.vnish: debug` dans `configuration.yaml`.

## Développement

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Les tests couvrent le client contre un faux mineur HTTP/RPC (`tests/fake_vnish.py`), l'analyse des
réponses, le config flow, la ré-authentification et chaque plateforme.
