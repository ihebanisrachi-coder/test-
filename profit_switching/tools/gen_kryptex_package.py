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
    ("quai-sha256", "quai", "QUAI"),
]

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
# Le Quai n'a pas d'estimation chez Kryptex (null) : il reste « indisponible » et n'entre pas dans le
# classement tant que Kryptex n'en publie pas une.
#
# Seul le gain PROPRE de chaque coin est compté : le minage fusionné (par exemple BTC + FB, annoncé par
# Kryptex) n'est pas ajouté, pour ne pas surestimer.
"""

GAIN = (
    "{% if value_json.estimated_profit_day is number %}"
    "{{ value_json.estimated_profit_day * 1e12 }}{% else %}unknown{% endif %}"
)
PRICE = "{% set last = value_json | last %}{{ last.price if last is mapping else 'unknown' }}"

# Rows of the ranking, built from the per-coin profit sensors (inlined where it is needed).
ROWS = """\
{% set ns = namespace(rows=[]) %}
{% for c in [@LABELS@] %}
  {% set v = states('sensor.kryptex_rentabilite_' ~ c | lower) %}
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
    return "\n".join(out)


def best_templates() -> str:
    labels = ", ".join(f"'{label}'" for _s, _c, label in COINS)
    rows = ROWS.replace("@LABELS@", labels)
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
            {{% for c in [{labels}] %}}
              {{% if states('sensor.kryptex_rentabilite_' ~ c | lower) | is_number %}}{{% set ok.coins = ok.coins + [c] %}}{{% endif %}}
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
