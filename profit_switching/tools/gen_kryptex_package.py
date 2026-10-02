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

# How each coin is really mined when it is NOT paid through Kryptex's autoexchange:
# id -> (pool name, helper id holding that pool's fee in %, default fee in %).
# Kryptex's `estimated_profit_day` is net of ITS OWN fee, so for these coins the gross figure is rebuilt
# (divided by 1 - Kryptex fee) and the fee of the pool actually used is applied instead. The defaults
# are assumptions: set the real fees in Home Assistant (and in `initial:` to keep them).
ROUTES = {
    "btc": ("f2pool", "kryptex_fee_btc", 2.5),
    "bch": ("tpool", "kryptex_fee_bch", 2.0),
}
AUTOEXCHANGE = "Kryptex (autoexchange)"
AUTOEXCHANGE_FEE_HELPER = "kryptex_autoexchange_fee"

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
#
# VOIES DE PAIEMENT. Le BTC est miné chez f2pool, le BCH chez tpool et le Quai chez K1Pool ; les autres coins
# passent par l'autoexchange de Kryptex. L'estimation de Kryptex étant nette de SES frais, pour le BTC et le
# BCH on reconstruit le gain brut puis on applique les frais du pool réellement utilisé ; pour les coins en
# autoexchange on applique les frais d'autoexchange. Les valeurs par défaut sont des hypothèses : réglez les
# vrais frais (entrées ci-dessous).

# Remis à ces valeurs à chaque redémarrage de Home Assistant : écrivez ici les valeurs réglées.
"""

def helpers() -> str:
    def block(key: str, name: str, step: float, default: float, low: float, high: float, icon: str,
              unit: str | None = "%") -> str:
        lines = [
            f"  {key}:",
            f'    name: "{name}"',
            f"    icon: {icon}",
            f"    min: {low}",
            f"    max: {high}",
            f"    step: {step}",
            f"    initial: {default}",
        ]
        if unit:
            lines.append(f'    unit_of_measurement: "{unit}"')
        return "\n".join(lines + ["    mode: box"])

    out = [
        "input_number:",
        block("k1pool_quai_factor", "Quai (K1Pool) : correction du gain", 0.05, 1, 0.1, 10, "mdi:tune", None),
        block(AUTOEXCHANGE_FEE_HELPER, "Kryptex : frais d'autoexchange", 0.1, 0, 0, 10, "mdi:percent"),
    ]
    for cid, (pool, helper, default) in ROUTES.items():
        label = next(lab for _s, c, lab in COINS if c == cid)
        out.append(block(helper, f"Frais {pool} ({label})", 0.1, default, 0, 10, "mdi:percent"))
    return "\n".join(out)


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
        if cid in ROUTES:
            _pool, helper, _default = ROUTES[cid]
            fee_helper = f"input_number.{helper}"
            # gross = Kryptex's net estimate / (1 - Kryptex fee), then the fee of the pool really used
            value = (
                f"(states('{gain}') | float / (1 - state_attr('{gain}', 'fee') | float)"
                f" * states('{price}') | float * (1 - states('{fee_helper}') | float / 100))"
            )
            ready = (
                f"states('{gain}') | is_number and states('{price}') | is_number"
                f" and state_attr('{gain}', 'fee') | is_number and states('{fee_helper}') | is_number"
            )
        else:
            fee_helper = f"input_number.{AUTOEXCHANGE_FEE_HELPER}"
            value = (
                f"(states('{gain}') | float * states('{price}') | float"
                f" * (1 - states('{fee_helper}') | float / 100))"
            )
            ready = (
                f"states('{gain}') | is_number and states('{price}') | is_number"
                f" and states('{fee_helper}') | is_number"
            )
        out += [
            f'      - name: "Kryptex rentabilité {label}"',
            f"        unique_id: kryptex_profit_{cid}",
            '        unit_of_measurement: "USD/TH/jour"',
            "        state: >-",
            f"          {{{{ {value} | round(5) }}}}",
            "        availability: >-",
            f"          {{{{ {ready} }}}}",
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
    route_of = {label: ROUTES[cid][0] if cid in ROUTES else AUTOEXCHANGE for _s, cid, label in COINS}
    route_of["QUAI"] = "K1Pool"
    routes = "{" + ", ".join(f"'{k}': '{v}'" for k, v in route_of.items()) + "}"
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
          voies: >-
            {{{{ {routes} }}}}
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
        + helpers()
        + "\n"
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
