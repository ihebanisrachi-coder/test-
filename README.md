# Vnish pour Home Assistant

Intégration personnalisée (HACS) pour piloter un mineur Antminer équipé du firmware **Vnish /
HashCore** depuis Home Assistant, via l'API locale du mineur (aucun cloud). Elle expose des entités
utilisables directement dans les automatisations : couper/relancer le minage, limiter la puissance,
changer de preset ou de pool, redémarrer, et surveiller hashrate, consommation, températures,
ventilateurs et cartes hash.

## Installation

**Avec HACS** : *HACS → ⋮ → Dépôts personnalisés* → ajouter ce dépôt (catégorie *Intégration*),
installer « Vnish », redémarrer Home Assistant.

**À la main** : copier `custom_components/vnish/` dans le dossier `custom_components/` de votre
configuration Home Assistant, puis redémarrer.

Ensuite : *Paramètres → Appareils et services → Ajouter une intégration → Vnish*, saisir l'adresse IP
du mineur et le mot de passe de son interface web (par défaut : `admin`).
Prérequis : Home Assistant 2025.1 ou plus récent (testé avec 2026.2), mineur joignable depuis Home
Assistant (port 80 pour l'API ; le port RPC 4028 n'est qu'un secours pour le hashrate et les pools).

*Options* (⚙ sur l'intégration) : intervalle de relevé, 30 s par défaut (10 à 600 s).

## Entités

`<mineur>` est le nom d'hôte du mineur.

**Commandes**

| Entité | Rôle |
|---|---|
| `switch.<mineur>_mining` | Arrête (`mining/stop`) / relance le minage : `mining/start` après un arrêt, `mining/resume` après une pause, avec l'autre en secours |
| `button.<mineur>_pause_mining` / `_resume_mining` | Met en pause / reprend le minage |
| `button.<mineur>_restart_mining` | Relance uniquement le minage |
| `button.<mineur>_reboot` | Redémarre le mineur |
| `number.<mineur>_throttle` | Limitation de 20 à 100 % de l'hashrate et de la puissance (100 = pas de limitation) |
| `select.<mineur>_preset` | Preset d'autotune actif, donc la puissance ; le libellé (« 3250 watt ~ 110 TH ») est dans les attributs |
| `select.<mineur>_active_pool` | Pool **actif** : `1`, `2`, `3` (= position dans la table de pools de Vnish ; l'URL de chaque numéro est dans les attributs, jamais les identifiants) |
| `button.<mineur>_use_pool_N` | Un bouton par pool configuré (N = 1, 2, 3), même effet que le sélecteur |

**Mesures**

| Entité | Rôle |
|---|---|
| `sensor.<mineur>_state` | État : `mining`, `initializing`, `starting`, `auto-tuning`, `restarting`, `shutting-down`, `stopped`, `failure` |
| `sensor.<mineur>_hashrate` | Hashrate temps réel (TH/s ; GH/s pour un mineur Scrypt) |
| `sensor.<mineur>_power` | Consommation en W (`power_consumption`) |
| `sensor.<mineur>_efficiency` | J/TH, calculé |
| `sensor.<mineur>_chip_temperature` / `_pcb_temperature` | Température max des puces / cartes |
| `sensor.<mineur>_fan_speed` | Vitesse globale des ventilateurs (%) |
| `binary_sensor.<mineur>_problem` | Allumé si le mineur ou une carte est en panne, ou un ventilateur perdu ; la liste est dans l'attribut `problems` |
| `sensor.<mineur>_expected_hashrate`, `_hardware_errors`, `_fan_N`, `_board_N_hashrate`, `_board_N_temperature`, `_board_N_state` | Diagnostic : hashrate attendu, taux d'erreurs matérielles, ventilateurs et cartes une par une |

### Changement de pool

Le changement de pool appelle l'endpoint de l'API `POST /mining/switch-pool` avec `{"pool_id": N}` :
seul le pool **actif** change, la table de pools n'est pas modifiée et le minage n'est pas relancé. Le
changement n'est probablement pas persistant (après un redémarrage du minage ou du mineur, il revient à
son pool principal configuré) ; pour ajouter ou réordonner des pools, passez par l'interface Vnish. Le
pool de commission (« DevFee ») n'est jamais proposé. Le pool actif vient de `/summary`
(`pools[].status == "active"`), ou à défaut de la commande RPC `pools` ; il est « inconnu » si aucune des
deux ne le fournit.

### Presets

Le menu `select.<mineur>_preset` ne propose que les presets déjà **réglés** (« tuned ») : en choisir un
non réglé lancerait un autotune de plusieurs heures. Pour en régler un nouveau, utilisez l'interface Vnish.

Changer de preset n'envoie au mineur que le **nom** du preset ; c'est le mineur qui applique alors les
fréquences et tensions réglées de ce preset. L'intégration relance le minage si le mineur le demande
(`restart_required`), puis relit le réglage pour confirmer. Le preset affiché est celui réellement appliqué
(`perf-summary`), qui suit aussi le changement automatique de preset ; il est « inconnu » en overclock
manuel.

> **Version 0.5.0 et antérieures** : le changement de preset renvoyait aussi l'ancien bloc
> d'overclock (fréquences, tension, réglages par puce) et pouvait écraser le réglage du preset choisi
> avec les valeurs du précédent. Si vous les avez utilisées, vérifiez dans l'interface Vnish (onglet
> Autotune) que vos presets sont toujours marqués « tuned » et non « modified », et relancez l'autotune
> des presets concernés si besoin. Si le changement automatique de preset (« preset switcher ») est
> activé, il peut aussi reprendre la main sur un choix manuel.

La limitation (`mining/throttle`) suit la même règle de redémarrage : le minage n'est relancé que si le
mineur répond qu'un redémarrage est nécessaire.

## Automatisations

Exemples prêts à adapter dans [`examples/automations.yaml`](examples/automations.yaml) : pause aux
heures pleines, preset ou limitation suivant le surplus solaire, bascule de pool, protection surchauffe,
alerte panne ou mineur hors ligne.

```yaml
actions:
  - action: number.set_value
    target: {entity_id: number.antminer_s19_throttle}
    data: {value: 60}
  - action: select.select_option
    target: {entity_id: select.antminer_s19_active_pool}
    data: {option: "2"}
```

## À valider sur votre mineur

L'intégration a été écrite à partir de la documentation de l'API HashCore/Vnish et testée contre un
faux mineur, **pas contre un mineur réel**. Deux chemins d'endpoint ne figuraient pas dans la
documentation consultée et sont déduits de la structure de l'API ; si l'un d'eux est faux, HA affiche une
erreur `HTTP 404` explicite et seule la fonction concernée est touchée :

- `POST /mining/switch-pool` (changement de pool),
- `POST /mining/throttle` (limitation).

Les autres endpoints (`summary`, `info`, `settings`, `autotune/presets`, `mining/*`, `system/reboot`) et
les champs lus sont ceux de la documentation. Une valeur introuvable donne une entité « inconnue », jamais
une erreur.

**Diagnostic** : *Paramètres → Appareils et services → Vnish → ⋮ → Télécharger les diagnostics* produit un
fichier d'où mots de passe, identifiants de pool, adresses IP/MAC et numéros de série sont retirés.
La sonde `tools/vnish_probe.py` (lecture seule, bibliothèque standard) fait de même depuis n'importe quelle
machine du réseau :

```bash
python3 tools/vnish_probe.py 192.168.1.50 --password admin > probe.json
```

Elle enregistre les réponses de `info`, `summary`, `status`, `settings`, `autotune/presets`,
`perf-summary`, `model` et du RPC (`summary`, `pools`), plus la liste des endpoints si le mineur publie sa
spécification (identifiants masqués, adresse MAC tronquée ; relisez avant de partager).

## Dépannage

- **« Impossible de joindre le mineur »** : mauvaise IP, ou le mineur ne tourne pas sous Vnish.
- **« Mot de passe incorrect »** : c'est le mot de passe de l'interface web ; en cas de changement
  ultérieur, Home Assistant propose de se ré-authentifier.
- **Pool ou limitation en erreur 404** : voir « À valider sur votre mineur ».
- **Journaux détaillés** : `logger: logs: custom_components.vnish: debug` dans `configuration.yaml`.

## Développement

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Les tests couvrent le client contre un faux mineur HTTP/RPC (`tests/fake_vnish.py`), l'analyse des
réponses, le config flow (réauthentification, options), les diagnostics et chaque plateforme.
