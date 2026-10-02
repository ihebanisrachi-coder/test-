#!/usr/bin/env python3
"""Generate packages/kryptex_best_sha256.yaml (the same templates repeated for each coin).

    python3 gen_kryptex_package.py

To follow another SHA-256 coin of Kryptex, add it to COINS (pool slug, id used in entity names,
label) and run this script again. A test checks that the committed file is the generator's output.
"""

from __future__ import annotations

from pathlib import Path

# (pool slug in the Kryptex URLs, id used in entity names, label shown in Home Assistant)
COINS = [
    ("btc", "btc", "BTC"),
    ("bch", "bch", "BCH"),
    ("fb", "fb", "FB"),
    ("xec", "xec", "XEC"),
    ("dgb", "dgb", "DGB"),
    ("bsv", "bsv", "BSV"),
]

# Kryptex publishes no estimate for Quai (null): it is computed from K1Pool's network figures, inside
# this same package (own sensors and own calibration knob, named k1pool_*), and joins the ranking.
QUAI_ENTITY = "sensor.k1pool_rentabilite_quai"

HEADER = """\
# Coin SHA-256 le plus rentable selon Kryptex, en USD par jour pour 1 TH/s (frais du pool déduits).
# FICHIER GÉNÉRÉ par tools/gen_kryptex_package.py : pour ajouter un coin, modifiez la liste COINS du
# script puis relancez-le, plutôt que ce fichier.
#
# Ce package est INDÉPENDANT de tout mineur et de l'intégration Vnish : il ne lit que l'API publique de
# Kryptex. Installation : copiez-le dans config/packages/ (après avoir activé les packages dans
# configuration.yaml :  homeassistant: { packages: !include_dir_named packages }), puis redémarrez.
#
# Pour chaque coin : `Kryptex gain` = coin gagné par TH/s et par jour (`estimated_profit_day` x 1e12),
# `Kryptex prix` = dernier point de la courbe de prix (USD), `Kryptex rentabilité` = gain x prix, sans minage fusionné.
# Le Quai n'a pas d'estimation chez Kryptex (null) : il est calculé depuis K1Pool par les capteurs
# `K1Pool gain Quai` et `K1Pool rentabilité Quai`. Formule standard de minage : récompense par bloc x
# (1 TH/s x 86 400 s) / difficulté du réseau, frais du pool déduits. La difficulté de K1Pool recoupe celle de
# Kryptex à ~5 % près. Elle n'a pas été vérifiée sur des gains réels : affinez-la avec
# `Quai (K1Pool) : correction du gain` (voir le README).
#
# Seul le gain PROPRE de chaque coin est compté : le minage fusionné (par exemple BTC + FB, annoncé par
# Kryptex) n'est pas ajouté, pour ne pas surestimer.

# Remis à cette valeur à chaque redémarrage de Home Assistant : écrivez ici la valeur calibrée.
input_number:
  k1pool_quai_factor:
    name: "Quai (K1Pool) : correction du gain"
    icon: mdi:tune
    min: 0.1
    max: 10
    step: 0.05
    initial: 1
    mode: box
"""

GAIN = (
    "{% if value_json.estimated_profit_day is number %}"
    "{{ value_json.estimated_profit_day * 1e12 }}{% else %}unknown{% endif %}"
)
K1POOL_GAIN = (
    "{% set j = value_json %}"
    "{% if j.coinReward is number and j.networkDiff is number and j.networkDiff > 0 %}"
    "{{ (j.coinReward * 86400 * 1e12 / j.networkDiff) | round(4) }}"
    "{% else %}unknown{% endif %}"
)
PRICE = "{% set last = value_json | last %}{{ last.price if last is mapping else 'unknown' }}"

# Rows of the ranking, built from the per-coin profit sensors (inlined where it is needed).
ROWS = """\
{% set ns = namespace(rows=[]) %}
{% for c, entity in @SOURCES@.items() %}
  {% set v = states(entity) %}
  {% if v | is_number %}{% set ns.rows = ns.rows + [{'coin': c, 'usd': v | float}] %}{% endif %}
{% endfor %}
{% set rows = ns.rows | sort(attribute='usd', reverse=true) %}"""


def rest() -> str:
    out = ["", "# --- Données Kryptex ---------------------------------------------------------------", "rest:"]
    for slug, cid, label in COINS:
        out += [
            f"  - resource: https://pool.kryptex.com/{slug}/api/v1/pool/info",
            "    scan_interval: 600",
            "    sensor:",
            f'      - name: "Kryptex gain {label}"',
            f"        unique_id: kryptex_gain_{cid}",
            f'        unit_of_measurement: "{label}/TH/jour"',
            f'        value_template: "{GAIN}"',
            "        json_attributes:",
            "          - fee",
            f"  - resource: https://pool.kryptex.com/api/v1/coin/{slug}/price/chart",
            "    scan_interval: 1800   # la courbe a un point par heure",
            "    sensor:",
            f'      - name: "Kryptex prix {label}"',
            f"        unique_id: kryptex_prix_{cid}",
            '        unit_of_measurement: "USD"',
            f'        value_template: "{PRICE}"',
        ]
    out += [
        "",
        "  # K1Pool : Kryptex n'a pas d'estimation pour le Quai, on la calcule (voir l'en-tête).",
        "  - resource: https://k1pool.com/api/stats/quaisha256",
        "    scan_interval: 600",
        "    sensor:",
        '      - name: "K1Pool gain Quai"',
        "        unique_id: k1pool_gain_quai",
        '        unit_of_measurement: "QUAI/TH/jour"',
        f'        value_template: "{K1POOL_GAIN}"',
        "        json_attributes:",
        "          - coinPriceUsd",
        "          - coinPoolFee",
    ]
    return "\n".join(out)


def per_coin_templates() -> str:
    out = []
    for _slug, cid, label in COINS:
        gain, price = f"sensor.kryptex_gain_{cid}", f"sensor.kryptex_prix_{cid}"
        out += [
            f'      - name: "Kryptex rentabilité {label}"',
            f"        unique_id: kryptex_profit_{cid}",
            '        unit_of_measurement: "USD/TH/jour"',
            "        state: >-",
            f"          {{{{ (states('{gain}') | float * states('{price}') | float) | round(5) }}}}",
            "        availability: >-",
            f"          {{{{ states('{gain}') | is_number and states('{price}') | is_number }}}}",
        ]
    out += [
        '      - name: "K1Pool rentabilité Quai"',
        "        unique_id: k1pool_profit_quai",
        '        unit_of_measurement: "USD/TH/jour"',
        "        state: >-",
        "          {{ (states('sensor.k1pool_gain_quai') | float",
        "              * state_attr('sensor.k1pool_gain_quai', 'coinPriceUsd') | float",
        "              * (1 - state_attr('sensor.k1pool_gain_quai', 'coinPoolFee') | float / 100)",
        "              * states('input_number.k1pool_quai_factor') | float) | round(5) }}",
        "        availability: >-",
        "          {{ states('sensor.k1pool_gain_quai') | is_number",
        "             and state_attr('sensor.k1pool_gain_quai', 'coinPriceUsd') | is_number",
        "             and state_attr('sensor.k1pool_gain_quai', 'coinPoolFee') | is_number",
        "             and states('input_number.k1pool_quai_factor') | is_number }}",
    ]
    return "\n".join(out)


def best_templates() -> str:
    sources = {label: f"sensor.kryptex_rentabilite_{cid}" for _s, cid, label in COINS} | {
        "QUAI": QUAI_ENTITY
    }
    mapping = "{" + ", ".join(f"'{k}': '{v}'" for k, v in sources.items()) + "}"
    labels = ", ".join(f"'{label}'" for label in sources)
    rows = ROWS.replace("@SOURCES@", mapping)
    indented = "\n".join("          " + line for line in rows.splitlines())
    attr = "\n".join("            " + line for line in rows.splitlines())
    return f"""\
      - name: "Meilleur coin SHA256 (Kryptex)"
        unique_id: kryptex_best_sha256
        icon: mdi:trophy
        state: >-
{indented}
          {{{{ rows[0].coin if rows else 'unknown' }}}}
        availability: >-
{indented}
          {{{{ rows | length > 0 }}}}
        attributes:
          usd_th_jour: >-
{attr}
            {{{{ rows[0].usd if rows else none }}}}
          classement: >-
{attr}
            {{% set out = namespace(lines=[]) %}}
            {{% for r in rows %}}{{% set out.lines = out.lines + [r.coin ~ ' = ' ~ (r.usd | round(5))] %}}{{% endfor %}}
            {{{{ out.lines }}}}
          indisponibles: >-
            {{% set ok = namespace(coins=[]) %}}
            {{% for c, entity in {mapping}.items() %}}
              {{% if states(entity) | is_number %}}{{% set ok.coins = ok.coins + [c] %}}{{% endif %}}
            {{% endfor %}}
            {{{{ [{labels}] | reject('in', ok.coins) | list }}}}

      - name: "Gain du meilleur coin SHA256"
        unique_id: kryptex_best_sha256_usd
        unit_of_measurement: "USD/TH/jour"
        icon: mdi:currency-usd
        state: "{{{{ state_attr('sensor.meilleur_coin_sha256_kryptex', 'usd_th_jour') | round(5) }}}}"
        availability: "{{{{ state_attr('sensor.meilleur_coin_sha256_kryptex', 'usd_th_jour') is number }}}}"
"""


def render() -> str:
    return (
        HEADER
        + rest()
        + "\n\n# --- Rentabilité par coin, puis classement --------------------------------------------"
        + "\ntemplate:\n  - sensor:\n"
        + per_coin_templates()
        + "\n\n"
        + best_templates()
    )


if __name__ == "__main__":
    target = Path(__file__).parent.parent / "packages" / "kryptex_best_sha256.yaml"
    target.write_text(render())
    print(f"written {target}")
