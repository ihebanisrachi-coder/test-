# Bascule du pool selon la rentabilité (BTC / BSV / Quai)

Projet **indépendant** de l'intégration Vnish du dépôt (`custom_components/vnish/`) : ce sont des
« packages » Home Assistant, sans code Python, qui comparent la rentabilité de trois pools de minage et
peuvent basculer le pool actif du mineur sur le plus rentable.

| Fichier | Rôle | Dépend de |
|---|---|---|
| [`packages/pool_profit.yaml`](packages/pool_profit.yaml) | Lit les API Kryptex, K1Pool et CoinGecko ; calcule les capteurs `Rentabilité BTC / BSV / Quai` et `Meilleur pool` | Rien (aucun mineur) |
| [`packages/pool_profit_switch.yaml`](packages/pool_profit_switch.yaml) | Automatisation qui bascule le pool actif | Le premier package, et l'intégration Vnish (3 entités à renseigner) |
| [`tools/pool_probe.py`](tools/pool_probe.py) | Sonde en lecture seule des API de pools, pour vérifier les champs et les prix | Rien |
| [`tests/`](tests/) | Tests sur de vraies réponses des pools et le moteur de Home Assistant | |

Vous pouvez n'installer que le premier package, pour **observer** la rentabilité sans rien automatiser.

## Installation

1. Activez les packages dans `configuration.yaml` si ce n'est pas fait :
   `homeassistant: { packages: !include_dir_named packages }`.
2. Copiez `pool_profit.yaml` dans `config/packages/` ; ajoutez `pool_profit_switch.yaml` pour la bascule.
3. Dans `pool_profit_switch.yaml`, remplacez `antminer_s19` par le nom de votre mineur dans Home Assistant
   (trois entités, tout en haut de l'automatisation).
4. Redémarrez Home Assistant.

Numéros de pool = position dans la table de pools du mineur : par défaut 1 = BTC (f2pool), 2 = BSV
(Kryptex), 3 = Quai (K1Pool).

## Ce que fait le projet

- Les capteurs `Rentabilité BTC`, `Rentabilité BSV`, `Rentabilité Quai` donnent les **USD gagnés par jour
  pour 1 TH/s, frais du pool déduits**, rafraîchis toutes les 10 minutes. Les trois pools minent en
  SHA-256 sur le même matériel : la consommation est la même et s'annule, on compare le revenu.
- `Meilleur pool` (1, 2 ou 3) désigne le plus rentable ; il est indisponible si une des trois valeurs manque.
- L'automatisation tourne toutes les 10 minutes et bascule seulement si : l'interrupteur
  `Bascule auto des pools` est allumé, le mineur mine sans panne, le gain dépasse **5 %** et le pool actif
  n'a pas changé depuis **30 min** (réglables dans `Gain minimal…` et `Durée minimale…`). Rien ne bascule
  sur des données partielles.
- **L'interrupteur est éteint au premier démarrage** : observez d'abord les capteurs, calibrez le Quai
  (ci-dessous), puis allumez-le.

## Sources des données

| Donnée | Source |
|---|---|
| Gain BTC et BSV par TH/s | Kryptex, `pool/info` → `estimated_profit_day` (coin par H/s et par jour, frais déduits ; recoupé avec le calcul théorique à 1-2 % près) |
| Gain Quai par TH/s | Calculé depuis K1Pool `stats` : récompense × blocs par jour ÷ hashrate du réseau (Kryptex n'a pas d'estimation pour le Quai) |
| Prix du Quai | K1Pool (`coinPriceUsd`) |
| Prix du BTC et du BSV | CoinGecko (`bitcoin`, `bitcoin-cash-sv`) : Kryptex n'a pas de prix pour le BSV |

## À calibrer : le gain du Quai

Les deux pools ne s'accordent pas sur le temps de bloc du Quai (K1Pool : 4,8 s, Kryptex : 1,13 s), ce qui
change l'estimation d'un facteur d'environ 4,3 : le Quai vaudrait environ 56 % du BTC avec le calcul de
K1Pool, 244 % avec celui de Kryptex. Le projet utilise celui de K1Pool. Pour le caler sur la réalité,
regardez combien de QUAI vous gagnez par jour sur K1Pool (moyenne sur plusieurs jours, le PPLNS fluctue) et
réglez `Correction du gain Quai` à :

> facteur = (QUAI gagnés par jour ÷ votre hashrate en TH/s) ÷ (valeur de `Gain brut Quai` × 0,98)

## Limites

Ce sont des gains **estimés** : la chance, le mode de paiement (PPS/PPLNS), les seuils de retrait et le
délai de maturation des récompenses diffèrent selon les pools, et le Quai est un coin peu liquide. Les
frais de f2pool sont réglés à 2,5 % par défaut (`Frais du pool BTC`, à vérifier sur votre compte). Chaque
changement de pool coûte quelques parts en cours, d'où le seuil de gain et le délai minimal.

## Vérifier les API (lecture seule)

```bash
curl -O https://raw.githubusercontent.com/ihebanisrachi-coder/test-/main/profit_switching/tools/pool_probe.py
python3 pool_probe.py > pools.json
```

Elle interroge les points d'accès publics (aucun compte ni identifiant) et résume chaque réponse.
Si `main` n'est pas à jour, remplacez `main` par le nom de la branche de travail.

## Tests

À la racine du dépôt (voir `requirements_test.txt`) : `pytest profit_switching/tests`. Les tests lisent de
vraies réponses des pools (`tests/data/`), exécutent les capteurs et l'automatisation dans Home Assistant,
et vérifient que le projet reste indépendant du module Vnish.
