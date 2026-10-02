# Rentabilité des pools de minage : classement Kryptex et bascule automatique

Projet **indépendant** de l'intégration Vnish du dépôt (`custom_components/vnish/`) : ce sont des
« packages » Home Assistant, sans code d'intégration, qui font deux choses séparées :

1. **Afficher le coin SHA-256 le plus rentable selon Kryptex** (`kryptex_best_sha256.yaml`) ;
2. **Comparer vos trois pools** (BTC / BSV / Quai) et basculer le pool actif du mineur sur le plus rentable
   (`pool_profit.yaml` + `pool_profit_switch.yaml`).

| Fichier | Rôle | Dépend de |
|---|---|---|
| [`packages/kryptex_best_sha256.yaml`](packages/kryptex_best_sha256.yaml) | Classe les coins SHA-256 de Kryptex et le Quai (K1Pool) par rentabilité (USD/TH/jour) et affiche le meilleur | Rien (aucun mineur, aucun autre package) |
| [`dashboard/kryptex_best_sha256_card.yaml`](dashboard/kryptex_best_sha256_card.yaml) | Carte de tableau de bord pour l'afficher | Le package ci-dessus |
| [`packages/pool_profit.yaml`](packages/pool_profit.yaml) | Lit les API Kryptex, K1Pool et CoinGecko ; calcule les capteurs `Rentabilité BTC / BSV / Quai` et `Meilleur pool` | Rien (aucun mineur) |
| [`packages/pool_profit_switch.yaml`](packages/pool_profit_switch.yaml) | Automatisation qui bascule le pool actif | Le premier package, et l'intégration Vnish (3 entités à renseigner) |
| [`tools/pool_probe.py`](tools/pool_probe.py) | Sonde en lecture seule des API de pools, pour vérifier les champs et les prix | Rien |
| [`tools/gen_kryptex_package.py`](tools/gen_kryptex_package.py) | Génère `kryptex_best_sha256.yaml` ; pour suivre un autre coin, ajoutez-le à sa liste | Rien |
| [`tests/`](tests/) | Tests sur de vraies réponses des pools et le moteur de Home Assistant | |

Chaque package s'installe seul. En particulier, `kryptex_best_sha256.yaml` et `pool_profit.yaml` servent à
**observer** sans rien automatiser.

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

## Coin SHA-256 le plus rentable selon Kryptex

Installez `packages/kryptex_best_sha256.yaml` (même procédure : `config/packages/`, puis redémarrage) et,
si vous voulez l'afficher, collez `dashboard/kryptex_best_sha256_card.yaml` dans une carte manuelle.

Pour chaque coin SHA-256 de Kryptex (BTC, BCH, FB, XEC, DGB, BSV), puis le Quai depuis K1Pool :

- `Kryptex gain` : coin gagné par TH/s et par jour, frais du pool déduits (`estimated_profit_day`) ;
- `Kryptex prix` : dernier point de la courbe de prix de Kryptex, en USD (un point par heure) ;
- `Kryptex rentabilité` : gain × prix, en **USD par jour pour 1 TH/s**.

Puis `Meilleur coin SHA256 (Kryptex)` donne le coin en tête, avec en attributs le `classement` complet, les
coins `indisponibles` et `usd_th_jour` ; `Gain du meilleur coin SHA256` donne sa valeur. Un coin sans donnée
sort du classement sans bloquer les autres. Les gains sont rafraîchis toutes les 10 minutes, les prix toutes
les 30 minutes.

**Minage fusionné non compté.** Le pool BTC de Kryptex annonce `mergemining: FB` (minage fusionné avec
Fractal Bitcoin). Ce gain **n'est pas ajouté** : chaque coin est évalué sur son seul `estimated_profit_day`,
pour ne pas surestimer. Avec ces chiffres, le classement place le BSV devant le BTC.

**Voies de paiement et frais.** Le gain affiché dépend de la façon dont chaque coin est réellement miné.
L'estimation de Kryptex (`estimated_profit_day`) est nette de **ses propres** frais ; le package en tient compte :

| Coin | Voie | Calcul |
|---|---|---|
| BTC | f2pool | gain brut reconstitué (estimation ÷ (1 − frais Kryptex)), puis frais f2pool |
| BCH | tpool | idem, avec les frais de tpool |
| Quai | K1Pool | calcul depuis K1Pool, frais lus dans l'API (2 %) |
| FB, XEC, DGB, BSV | autoexchange de Kryptex | estimation Kryptex, puis frais d'autoexchange |

Les frais se règlent dans Home Assistant : `Frais f2pool (BTC)`, `Frais tpool (BCH)` et
`Kryptex : frais d'autoexchange`. **Leurs valeurs par défaut sont des hypothèses de ma part** (2,5 %, 2 % et
0 %) : mettez les vrais frais, et écrivez-les dans les lignes `initial:` du fichier pour qu'ils survivent à un
redémarrage. L'attribut `voies` du capteur `Meilleur coin SHA256 (Kryptex)` indique la voie de chaque coin, et
la carte l'affiche à côté de chaque ligne du classement. Le gain du BCH chez tpool est estimé à partir des
chiffres du réseau de Kryptex : tpool n'a pas été interrogé.

**Quai, depuis K1Pool, dans ce même package.** Kryptex ne publie pas d'estimation pour le Quai (`null`). Le
package le calcule donc depuis K1Pool (`https://k1pool.com/api/stats/quaisha256`) avec la formule standard du
minage : récompense par bloc × (1 TH/s × 86 400 s) ÷ difficulté du réseau, × le prix du Quai, frais du pool
déduits. Capteurs : `K1Pool gain Quai` (QUAI par TH/s et par jour, brut) et `K1Pool rentabilité Quai` (USD par
TH/s et par jour). Aucun autre package n'est nécessaire.

*Pourquoi cette formule.* Une première version utilisait le temps de bloc (4,8 s chez K1Pool, 1,13 s chez
Kryptex) : les deux pools ne s'accordent pas, ce qui donnait des résultats d'un facteur 4,3 d'écart. La
difficulté, elle, est la même chez les deux (celle de Kryptex, convertie en hashes, recoupe celle de K1Pool à
5 % près), et le résultat (environ 0,042 USD/TH/jour) est du même ordre que le BTC et le BSV, comme on s'y attend
quand le hashrate migre vers le coin le plus rentable. **Elle n'a pas été vérifiée sur vos gains réels.** Pour
l'affiner, réglez `Quai (K1Pool) : correction du gain` à :

> facteur = (QUAI gagnés par jour ÷ votre hashrate en TH/s) ÷ (valeur de `K1Pool gain Quai` × 0,98)

(moyenne sur plusieurs jours, le PPLNS fluctue). Ce réglage revient à 1 à chaque redémarrage de Home Assistant :
une fois calibré, écrivez sa valeur dans la ligne `initial:` du fichier. Un facteur proche de 1 confirme la formule.

Ce sont des gains **estimés** par Kryptex : ils ne tiennent pas compte de la chance, des seuils de retrait
ni du délai de maturation des récompenses.

## Sources des données (bascule entre vos trois pools)

| Donnée | Source |
|---|---|
| Gain BTC et BSV par TH/s | Kryptex, `pool/info` → `estimated_profit_day` (coin par H/s et par jour, frais déduits ; recoupé avec le calcul théorique à 1-2 % près) |
| Gain Quai par TH/s | Calculé depuis K1Pool `stats` : récompense × blocs par jour ÷ hashrate du réseau (Kryptex n'a pas d'estimation pour le Quai) |
| Prix du Quai | K1Pool (`coinPriceUsd`) |
| Prix du BTC et du BSV | CoinGecko (`bitcoin`, `bitcoin-cash-sv`) : Kryptex n'a pas de prix pour le BSV |

## Gain du Quai dans `pool_profit.yaml`

Le package calcule le Quai de la même façon (formule standard, difficulté du réseau de K1Pool : voir plus haut),
et son réglage `Correction du gain Quai` sert à l'affiner sur vos gains réels :

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

Elle interroge les points d'accès publics (aucun compte ni identifiant), y compris tous les coins SHA-256 de
Kryptex, et résume chaque réponse.
Si `main` n'est pas à jour, remplacez `main` par le nom de la branche de travail.

## Tests

À la racine du dépôt (voir `requirements_test.txt`) : `pytest profit_switching/tests`. Les tests lisent de
vraies réponses des pools (`tests/data/`), exécutent les capteurs et l'automatisation dans Home Assistant,
et vérifient que le projet reste indépendant du module Vnish.
