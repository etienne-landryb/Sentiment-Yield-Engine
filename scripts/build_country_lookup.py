"""Generate config/country_lookup.yaml toward the ~193 UN member states.

Data-generation script, not a hand-typed table (per the brief). Run once, review
the diff, commit. Re-run any time data/coverage_sentiment.csv is refreshed with a
wider set of GDELT codes.

    python scripts/build_country_lookup.py

Sourcing:
  - Code -> name: GDELT's OWN lookup file, LOOKUP-COUNTRIES.TXT, at
    https://storage.googleapis.com/data.gdeltproject.org/api/v2/guides/LOOKUP-COUNTRIES.TXT
  - Code -> ISO2: an independent FIPS-10-4-to-ISO-3166 cross-reference
    (github.com/mysociety/gaze/blob/master/data/fips-10-4-to-iso-country-codes.csv),
    used to derive ISO3/region-lookup and to CATCH two real errors in GDELT's own
    file: `LO` is labelled "Czechoslovakia" but is actually Slovakia (ISO SK);
    `GV` is labelled "Equatorial Guinea" but is actually Guinea (ISO GN) —
    Equatorial Guinea is `EK`. Both corrected below.
  - CFA franc zone (14 members, pegged to EUR at a fixed 655.957): BCEAO/XOF
    (Benin, Burkina Faso, Cote d'Ivoire, Guinea-Bissau, Mali, Niger, Senegal, Togo)
    and BEAC/XAF (Cameroon, Central African Republic, Chad, Congo-Brazzaville,
    Equatorial Guinea, Gabon) — verified via worlddata.info / BCEAO (2026).
  - Officially dollarized (USD, no exchange rate exists): Ecuador, El Salvador,
    Marshall Islands, Micronesia, Palau, Panama, Timor-Leste — cross-checked
    against multiple 2026 currency-guide sources; exactly 7.
  - Hard USD pegs (own currency, fixed rate, decades-stable): Saudi Arabia (SAR
    3.75), UAE (AED 3.6725), Qatar (QAR 3.64), Bahrain (BHD 0.376), Oman (OMR
    0.3845), Jordan (JOD 0.709), Hong Kong (HKD ~7.75-7.85 linked exchange rate /
    currency board since 1983 — HKD has its own live FRED series, unlike the rest).
  - Deliberately EXCLUDED from the peg table: Kuwait (pegged to an undisclosed
    currency BASKET, not purely USD — doesn't fit a clean single peg_to) and
    Zimbabwe (monetary status has changed repeatedly and recently; not confidently
    verifiable as stable at time of writing). Both fall through to `floating`.
  - Extended this round (same standard: real, citable, decades-stable only):
    ECCU/XCD -> USD @ 2.70 (6 UN members: Antigua and Barbuda, Dominica, Grenada,
    St Kitts and Nevis, St Lucia, St Vincent and the Grenadines); Bosnia (BAM) ->
    EUR @ 1.95583 currency board since 1997; Comoros (KMF) -> EUR @ 491.96775
    since 1999; Bhutan (BTN) -> INR 1:1 since 1974; Nepal (NPR) -> INR 1.6:1 since
    1993; Lesotho/Namibia/Eswatini -> ZAR 1:1 via the Common Monetary Area. Anchor
    proxies (DEXINUS, DEXSFUS) used exactly as the CFA-zone DEXUSEU pattern.
  - Bulgaria adopted the euro on 2026-01-01 (real, dated event) — reclassified
    from floating-with-own-BGN to floating-with-EUR, folded into the euro area.

UN membership: derived from pycountry's full 249-entry ISO-3166-1 list minus a
documented 56-code exclusion set (dependent territories, SARs, Taiwan, Vatican
City, the State of Palestine as UN observers, and uninhabited entities) — the
count lands exactly on the UN's own official 193, which is the correctness check.
Written to data/un_member_states.csv. The core country_lookup is restricted to
these 193 PLUS three previously-justified non-UN exceptions retained for
substantial GDELT coverage and genuinely distinct currencies/markets: Hong Kong,
Macau, Taiwan. Kosovo is also kept (a real government, not a full UN member due
to contested recognition). Vatican City — included in an earlier round — is
DROPPED this round. Checked its actual coverage first: full 184/184-day, ~223
articles/day (data/coverage_sentiment.csv, code VT) — dense, not thin. Dropped
anyway: that volume is very likely global papal/diplomatic mentions (encyclicals,
Vatican statements on world affairs) via GDELT's co-mention attribution, not
Vatican-City-specific economic signal, so it doesn't cleanly fit the panel's
economic-sentiment thesis even though the raw day/article counts pass. Also has
no realistic market/currency mechanism beyond what Kosovo already represents
(both unilaterally euroized) — a second, independent reason to exclude it.

Excluded entirely: defunct/duplicate FIPS codes (RB = legacy pre-2008 Serbia dup
of RI; YI = defunct Serbia-and-Montenegro/Yugoslavia code retired 2006; OC =
unidentified, no confident source found), disputed/uninhabited islet catch-alls,
and non-UN-member dependent territories that would just duplicate a parent
state's currency.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COVERAGE_CSV = ROOT / "data" / "coverage_sentiment.csv"
OUT_PATH = ROOT / "config" / "country_lookup.yaml"
UN_MEMBERS_PATH = ROOT / "data" / "un_member_states.csv"
UN_CANDIDATES_PATH = ROOT / "data" / "un_candidates.csv"

# Non-UN-member ISO2 codes: dependent territories, Special Administrative Regions,
# Taiwan, UN-observer entities (Vatican City, State of Palestine), and uninhabited/
# administrative entities that still carry an ISO 3166-1 code. Subtracting this
# documented 56-entry set from pycountry's full 249-entry list lands EXACTLY on the
# UN's own official count of 193 — that arithmetic match is the correctness check.
NON_UN_ISO2 = {
    "AI", "AQ", "AS", "AW", "AX", "BL", "BM", "BQ", "BV", "CC", "CK", "CW", "CX",
    "EH", "FK", "FO", "GF", "GG", "GI", "GL", "GP", "GS", "GU", "HK", "HM", "IM",
    "IO", "JE", "KY", "MF", "MO", "MP", "MQ", "MS", "NC", "NF", "NU", "PF", "PM",
    "PN", "PR", "PS", "RE", "SH", "SJ", "SX", "TC", "TF", "TK", "TW", "UM", "VA",
    "VG", "VI", "WF", "YT",
}
# Non-UN entities kept anyway (substantial GDELT coverage, genuinely distinct
# currencies/markets) — Vatican City (VT) dropped this round despite dense real
# coverage (184/184 days, ~223 articles/day): almost certainly global papal/
# diplomatic mentions via co-mention attribution, not Vatican-specific economic
# signal — fails the panel's economic-sentiment thesis even though it clears the
# density threshold. See docstring for the full reasoning.
KEPT_NON_UN_EXCEPTIONS = {"HK", "MC", "TW", "KV"}  # FIPS codes (Hong Kong, Macau, Taiwan, Kosovo)

# ── code -> (name, iso2) : GDELT's own lookup + 2 verified corrections ──────────
# fmt: off
CODE_NAME_ISO2 = {
    "AF": ("Afghanistan", "AF"), "AL": ("Albania", "AL"), "AG": ("Algeria", "DZ"),
    "AN": ("Andorra", "AD"), "AO": ("Angola", "AO"), "AC": ("Antigua and Barbuda", "AG"),
    "AR": ("Argentina", "AR"), "AM": ("Armenia", "AM"), "AS": ("Australia", "AU"),
    "AU": ("Austria", "AT"), "AJ": ("Azerbaijan", "AZ"), "BF": ("Bahamas", "BS"),
    "BA": ("Bahrain", "BH"), "BG": ("Bangladesh", "BD"), "BB": ("Barbados", "BB"),
    "BO": ("Belarus", "BY"), "BE": ("Belgium", "BE"), "BH": ("Belize", "BZ"),
    "BN": ("Benin", "BJ"), "BT": ("Bhutan", "BT"), "BL": ("Bolivia", "BO"),
    "BK": ("Bosnia and Herzegovina", "BA"), "BC": ("Botswana", "BW"), "BR": ("Brazil", "BR"),
    "BX": ("Brunei", "BN"), "BU": ("Bulgaria", "BG"), "UV": ("Burkina Faso", "BF"),
    "BY": ("Burundi", "BI"), "CB": ("Cambodia", "KH"), "CM": ("Cameroon", "CM"),
    "CA": ("Canada", "CA"), "CV": ("Cape Verde", "CV"), "CT": ("Central African Republic", "CF"),
    "CD": ("Chad", "TD"), "CI": ("Chile", "CL"), "CH": ("China", "CN"),
    "CO": ("Colombia", "CO"), "CN": ("Comoros", "KM"), "CF": ("Congo (Republic of)", "CG"),
    "CG": ("Congo (Democratic Republic of)", "CD"), "CS": ("Costa Rica", "CR"),
    "IV": ("Cote d'Ivoire", "CI"), "HR": ("Croatia", "HR"), "CU": ("Cuba", "CU"),
    "CY": ("Cyprus", "CY"), "EZ": ("Czech Republic", "CZ"), "DA": ("Denmark", "DK"),
    "DJ": ("Djibouti", "DJ"), "DO": ("Dominica", "DM"), "DR": ("Dominican Republic", "DO"),
    "TT": ("Timor-Leste", "TL"), "EC": ("Ecuador", "EC"), "EG": ("Egypt", "EG"),
    "ES": ("El Salvador", "SV"), "EK": ("Equatorial Guinea", "GQ"), "ER": ("Eritrea", "ER"),
    "EN": ("Estonia", "EE"), "ET": ("Ethiopia", "ET"), "FJ": ("Fiji", "FJ"),
    "FI": ("Finland", "FI"), "FR": ("France", "FR"), "GB": ("Gabon", "GA"),
    "GA": ("Gambia", "GM"), "GG": ("Georgia", "GE"), "GM": ("Germany", "DE"),
    "GH": ("Ghana", "GH"), "GR": ("Greece", "GR"), "GJ": ("Grenada", "GD"),
    "GT": ("Guatemala", "GT"), "GV": ("Guinea", "GN"), "PU": ("Guinea-Bissau", "GW"),
    "GY": ("Guyana", "GY"), "HA": ("Haiti", "HT"), "HO": ("Honduras", "HN"),
    "HK": ("Hong Kong", "HK"), "HU": ("Hungary", "HU"), "IC": ("Iceland", "IS"),
    "IN": ("India", "IN"), "ID": ("Indonesia", "ID"), "IR": ("Iran", "IR"),
    "IZ": ("Iraq", "IQ"), "EI": ("Ireland", "IE"), "IS": ("Israel", "IL"),
    "IT": ("Italy", "IT"), "JM": ("Jamaica", "JM"), "JA": ("Japan", "JP"),
    "JO": ("Jordan", "JO"), "KZ": ("Kazakhstan", "KZ"), "KE": ("Kenya", "KE"),
    "KR": ("Kiribati", "KI"), "KV": ("Kosovo", None), "KU": ("Kuwait", "KW"),
    "KG": ("Kyrgyzstan", "KG"), "LA": ("Laos", "LA"), "LG": ("Latvia", "LV"),
    "LE": ("Lebanon", "LB"), "LT": ("Lesotho", "LS"), "LI": ("Liberia", "LR"),
    "LY": ("Libya", "LY"), "LS": ("Liechtenstein", "LI"), "LH": ("Lithuania", "LT"),
    "LU": ("Luxembourg", "LU"), "MC": ("Macau", "MO"), "MK": ("North Macedonia", "MK"),
    "MA": ("Madagascar", "MG"), "MI": ("Malawi", "MW"), "MY": ("Malaysia", "MY"),
    "MV": ("Maldives", "MV"), "ML": ("Mali", "ML"), "MT": ("Malta", "MT"),
    "RM": ("Marshall Islands", "MH"), "MR": ("Mauritania", "MR"), "MP": ("Mauritius", "MU"),
    "MX": ("Mexico", "MX"), "FM": ("Micronesia", "FM"), "MD": ("Moldova", "MD"),
    "MN": ("Monaco", "MC"), "MG": ("Mongolia", "MN"), "MJ": ("Montenegro", "ME"),
    "MO": ("Morocco", "MA"), "MZ": ("Mozambique", "MZ"), "BM": ("Myanmar", "MM"),
    "WA": ("Namibia", "NA"), "NR": ("Nauru", "NR"), "NP": ("Nepal", "NP"),
    "NL": ("Netherlands", "NL"), "NZ": ("New Zealand", "NZ"), "NU": ("Nicaragua", "NI"),
    "NG": ("Niger", "NE"), "NI": ("Nigeria", "NG"), "KN": ("North Korea", "KP"),
    "NO": ("Norway", "NO"), "MU": ("Oman", "OM"), "PK": ("Pakistan", "PK"),
    "PS": ("Palau", "PW"), "PM": ("Panama", "PA"), "PP": ("Papua New Guinea", "PG"),
    "PA": ("Paraguay", "PY"), "PE": ("Peru", "PE"), "RP": ("Philippines", "PH"),
    "PL": ("Poland", "PL"), "PO": ("Portugal", "PT"), "QA": ("Qatar", "QA"),
    "RO": ("Romania", "RO"), "RS": ("Russia", "RU"), "RW": ("Rwanda", "RW"),
    "SC": ("Saint Kitts and Nevis", "KN"), "ST": ("Saint Lucia", "LC"),
    "VC": ("Saint Vincent and the Grenadines", "VC"), "WS": ("Samoa", "WS"),
    "SM": ("San Marino", "SM"), "TP": ("Sao Tome and Principe", "ST"),
    "SA": ("Saudi Arabia", "SA"), "SG": ("Senegal", "SN"), "RI": ("Serbia", "RS"),
    "SE": ("Seychelles", "SC"), "SL": ("Sierra Leone", "SL"), "SN": ("Singapore", "SG"),
    "LO": ("Slovakia", "SK"), "SI": ("Slovenia", "SI"), "BP": ("Solomon Islands", "SB"),
    "SO": ("Somalia", "SO"), "SF": ("South Africa", "ZA"), "KS": ("South Korea", "KR"),
    "OD": ("South Sudan", "SS"), "SP": ("Spain", "ES"), "CE": ("Sri Lanka", "LK"),
    "SU": ("Sudan", "SD"), "NS": ("Suriname", "SR"), "WZ": ("Eswatini", "SZ"),
    "SW": ("Sweden", "SE"), "SZ": ("Switzerland", "CH"), "SY": ("Syria", "SY"),
    "TW": ("Taiwan", "TW"), "TI": ("Tajikistan", "TJ"), "TZ": ("Tanzania", "TZ"),
    "TH": ("Thailand", "TH"), "TO": ("Togo", "TG"), "TN": ("Tonga", "TO"),
    "TD": ("Trinidad and Tobago", "TT"), "TS": ("Tunisia", "TN"), "TU": ("Turkey", "TR"),
    "TX": ("Turkmenistan", "TM"), "TV": ("Tuvalu", "TV"), "UG": ("Uganda", "UG"),
    "UP": ("Ukraine", "UA"), "AE": ("United Arab Emirates", "AE"), "UK": ("United Kingdom", "GB"),
    "US": ("United States", "US"), "UY": ("Uruguay", "UY"), "UZ": ("Uzbekistan", "UZ"),
    "NH": ("Vanuatu", "VU"), "VT": ("Vatican City", "VA"), "VE": ("Venezuela", "VE"),
    "VM": ("Vietnam", "VN"), "YM": ("Yemen", "YE"), "ZA": ("Zambia", "ZM"),
    "ZI": ("Zimbabwe", "ZW"),
}
# fmt: on

# ── region assignment (cosmetic grouping for the map/sidebar, not a monetary claim) ──
REGION = {}
for c in ("US", "CA", "MX"):
    REGION[c] = "north_america"
for c in ("AR", "BL", "BR", "CI", "CO", "CS", "CU", "DR", "EC", "GY", "HA", "HO",
          "JM", "NU", "PM", "PA", "PE", "UY", "VE", "BB", "BH",
          "DO", "GJ", "GT", "SC", "ST", "VC", "AC", "BF", "ES", "NS", "TD"):
    REGION[c] = "latin_america"
for c in ("UK", "FR", "GM", "IT", "SP", "NL", "BE", "PO", "FI", "GR", "SW", "SZ",
          "NO", "DA", "PL", "AU", "HU", "EZ", "RO", "BU", "HR", "SI", "LO",
          "LG", "LH", "EN", "IC", "EI", "MT", "CY", "LU", "MN", "SM",
          "VT", "AL", "BK", "MK", "MJ", "RI", "MD", "UP", "BO", "GG",
          "AM", "AJ", "TU", "KV", "AN", "LS", "RS"):
    REGION[c] = "europe"
for c in ("JA", "CH", "IN", "AS", "NZ", "KS", "KN", "TW", "ID", "MY", "TH", "VM",
          "PK", "BG", "NP", "BT", "LA", "CB", "BX", "MG", "KZ", "KG", "TI", "TX",
          "UZ", "AF", "HK", "MC", "SN", "RP", "PP", "FJ", "NH", "WS", "TN", "KR",
          "TV", "NR", "BP", "MV", "FM", "PS", "RM", "TT", "CE", "BM"):
    REGION[c] = "asia_pacific"
# everything else defaults to africa_mideast (see main())

# ── ISO2 -> ISO 4217 currency code (standard reference data) ────────────────────
CURRENCY_OF_ISO2 = {
    "US": "USD", "CA": "CAD", "MX": "MXN", "AR": "ARS", "BR": "BRL", "CO": "COP",
    "PE": "PEN", "CL": "CLP", "VE": "VES", "UY": "UYU", "PY": "PYG", "BO": "BOB",
    "GY": "GYD", "SR": "SRD", "CR": "CRC", "GT": "GTQ", "HN": "HNL", "NI": "NIO",
    "HT": "HTG", "DO": "DOP", "CU": "CUP", "JM": "JMD", "BS": "BSD", "BB": "BBD",
    "TT": "TTD", "DM": "XCD", "GD": "XCD", "LC": "XCD", "VC": "XCD", "KN": "XCD",
    "AG": "XCD", "BZ": "BZD",
    "GB": "GBP", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "NL": "EUR",
    "BE": "EUR", "PT": "EUR", "FI": "EUR", "GR": "EUR", "IE": "EUR", "AT": "EUR",
    "LU": "EUR", "MT": "EUR", "CY": "EUR", "SK": "EUR", "SI": "EUR", "EE": "EUR",
    "LV": "EUR", "LT": "EUR", "MC": "EUR", "SM": "EUR", "VA": "EUR", "AD": "EUR",
    "SE": "SEK", "CH": "CHF", "NO": "NOK", "DK": "DKK", "PL": "PLN", "CZ": "CZK",
    "HU": "HUF", "RO": "RON", "BG": "BGN", "HR": "EUR", "AL": "ALL", "BA": "BAM",
    "MK": "MKD", "ME": "EUR", "RS": "RSD", "MD": "MDL", "UA": "UAH", "BY": "BYN",
    "RU": "RUB", "GE": "GEL", "AM": "AMD", "AZ": "AZN", "TR": "TRY", "IS": "ISK",
    "LI": "CHF",
    "JP": "JPY", "CN": "CNY", "IN": "INR", "AU": "AUD", "NZ": "NZD", "KR": "KRW",
    "KP": "KPW", "TW": "TWD", "ID": "IDR", "MY": "MYR", "TH": "THB", "VN": "VND",
    "PK": "PKR", "BD": "BDT", "NP": "NPR", "BT": "BTN", "LA": "LAK", "KH": "KHR",
    "BN": "BND", "MN": "MNT", "KZ": "KZT", "KG": "KGS", "TJ": "TJS", "TM": "TMT",
    "UZ": "UZS", "AF": "AFN", "HK": "HKD", "MO": "MOP", "SG": "SGD", "PH": "PHP",
    "MM": "MMK", "LK": "LKR",
    "PG": "PGK", "FJ": "FJD", "VU": "VUV", "WS": "WST", "TO": "TOP", "TV": "AUD",
    "NR": "AUD", "SB": "SBD", "KI": "AUD", "MV": "MVR",
    "SA": "SAR", "AE": "AED", "QA": "QAR", "BH": "BHD", "OM": "OMR", "KW": "KWD",
    "JO": "JOD", "IL": "ILS", "LB": "LBP", "SY": "SYP", "IQ": "IQD", "IR": "IRR",
    "YE": "YER", "EG": "EGP", "MA": "MAD", "DZ": "DZD", "TN": "TND", "LY": "LYD",
    "SD": "SDG", "SS": "SSP",
    "ZA": "ZAR", "NG": "NGN", "KE": "KES", "GH": "GHS", "ET": "ETB", "TZ": "TZS",
    "UG": "UGX", "RW": "RWF", "BI": "BIF", "ZM": "ZMW", "ZW": "ZWG", "MZ": "MZN",
    "MW": "MWK", "AO": "AOA", "NA": "NAD", "BW": "BWP", "LS": "LSL", "SZ": "SZL",
    "MG": "MGA", "MU": "MUR", "SC": "SCR", "KM": "KMF", "DJ": "DJF", "SO": "SOS",
    "ER": "ERN", "GM": "GMD", "SL": "SLE", "LR": "LRD", "GN": "GNF", "CV": "CVE",
    "MR": "MRU", "GQ": "XAF", "CF": "XAF", "TD": "XAF", "CD": "CDF", "CM": "XAF",
    "GA": "XAF", "BJ": "XOF", "BF": "XOF", "CI": "XOF", "GW": "XOF", "ML": "XOF",
    "NE": "XOF", "SN": "XOF", "TG": "XOF", "ST": "STN",
}
# Note: ISO2 "CG" (Republic of Congo/Brazzaville) is intentionally absent here —
# its currency is assigned via the CFA_XAF peg shortcut (FIPS code "CF") below,
# so this table only needs "CD" (Democratic Republic of the Congo, ISO2 CD, CDF).

# ── §2: sourced peg / dollarization reference table (SMALL and cited) ──────────
CFA_XAF = {"CM", "CT", "CD", "CF", "EK", "GB"}                # BEAC, peg 655.957/EUR
CFA_XOF = {"BN", "UV", "IV", "PU", "ML", "NG", "SG", "TO"}     # BCEAO, peg 655.957/EUR
DOLLARIZED = {"EC", "ES", "RM", "FM", "PS", "PM", "TT"}         # USD, no exchange rate
HARD_USD_PEG = {  # code -> (peg_rate str, fred_fx or None)
    "SA": ("3.75", None), "AE": ("3.6725", None), "QA": ("3.64", None),
    "BA": ("0.376", None), "MU": ("0.3845", None), "JO": ("0.709", None),
    "HK": ("~7.75-7.85 (linked exchange rate band)", "DEXHKUS"),
}
# Additional sourced pegs (verified this round, same standard as the sets above — real,
# citable, decades-stable arrangements only). code -> (currency, peg_to, peg_rate, fred_fx
# of the ANCHOR currency, used exactly as the CFA-zone pattern already does).
#   - ECCU/XCD -> USD @ 2.70 since 1976 (6 UN-member Eastern Caribbean states; Anguilla
#     and Montserrat also use XCD but are non-UN British territories, already excluded).
#   - Bosnia (BAM) -> EUR @ 1.95583, currency board since 1997.
#   - Comoros (KMF) -> EUR @ 491.96775, French monetary-cooperation peg since 1999
#     (administered separately from the BEAC/BCEAO CFA zone, same fixed-EUR-peg family).
#   - Bhutan (BTN) -> INR @ 1:1 since 1974; Nepal (NPR) -> INR @ 1.6:1 since 1993 (both
#     use India's own FRED series, DEXINUS, as the anchor proxy — same mechanical logic
#     as CFA members using DEXUSEU).
#   - Lesotho (LSL), Namibia (NAD), Eswatini (SZL) -> ZAR @ 1:1 via the Common Monetary
#     Area (CMA); anchor proxy is South Africa's own FRED series, DEXSFUS.
_ECCU_XCD = {"AC", "DO", "GJ", "SC", "ST", "VC"}  # Antigua&Barbuda, Dominica, Grenada,
                                                   # St Kitts&Nevis, St Lucia, St Vincent
OTHER_PEG = {
    **{c: ("XCD", "USD", "2.70", None) for c in _ECCU_XCD},
    "BK": ("BAM", "EUR", "1.95583", "DEXUSEU"),
    "CN": ("KMF", "EUR", "491.96775", "DEXUSEU"),
    "BT": ("BTN", "INR", "1:1", "DEXINUS"),
    "NP": ("NPR", "INR", "1.6:1", "DEXINUS"),
    "LT": ("LSL", "ZAR", "1:1", "DEXSFUS"),
    "WA": ("NAD", "ZAR", "1:1", "DEXSFUS"),
    "WZ": ("SZL", "ZAR", "1:1", "DEXSFUS"),
}
# Bulgaria adopted the euro on 2026-01-01, replacing the lev (BGN) it was floating-with-
# own-currency under previously — a real, dated event, not a guess. Currency override.
CURRENCY_OVERRIDE = {"BU": "EUR", "KV": "EUR"}  # KV=Kosovo, unilaterally euroized (as before)

# ── FRED DEX candidates: currency -> series id (H.10 release; test-fetch confirms) ──
FRED_DEX = {
    "EUR": "DEXUSEU", "JPY": "DEXJPUS", "GBP": "DEXUSUK", "CAD": "DEXCAUS",
    "CHF": "DEXSZUS", "CNY": "DEXCHUS", "BRL": "DEXBZUS", "MXN": "DEXMXUS",
    "INR": "DEXINUS", "KRW": "DEXKOUS", "SGD": "DEXSIUS", "ZAR": "DEXSFUS",
    "SEK": "DEXSDUS", "NOK": "DEXNOUS", "DKK": "DEXDNUS", "HKD": "DEXHKUS",
    "TWD": "DEXTAUS", "THB": "DEXTHUS", "MYR": "DEXMAUS", "NZD": "DEXUSNZ",
    "AUD": "DEXUSAL", "LKR": "DEXSLUS",
}

# ── td_index candidates: conservative; only reasonably well-known tickers ──────
#    (test-fetch confirms/rejects the rest — wrong guesses are safe, just filtered).
TD_INDEX = {
    "GB": "EWU", "DE": "DAX", "FR": "EWQ", "IT": "EWI", "ES": "EWP", "NL": "EWN",
    "BE": "EWK", "SE": "EWD", "CH": "EWL", "NO": "ENOR", "DK": "EDEN", "PL": "EPOL",
    "JP": "EWJ", "CN": "MCHI", "IN": "INDA", "AU": "EWA", "KR": "EWY", "TW": "EWT",
    "SG": "EWS", "MY": "EWM", "TH": "THD", "ID": "EIDO", "PH": "EPHE",
    "CA": "EWC", "MX": "EWW", "BR": "EWZ", "CL": "ECH", "CO": "GXG", "PE": "EPU",
    "ZA": "EZA", "EG": "EGPT", "IL": "EIS", "TR": "TUR", "SA": "KSA", "NZ": "ENZL",
}

# ── explicit drops (documented reasons; the loop only ever KEEPS what's in ────
#    CODE_NAME_ISO2 above, so these sets are auditability/documentation, not the
#    actual filter — nothing here was ever added to CODE_NAME_ISO2 in the first place) ──
DROP_LEGACY_NOTE = {
    "RB": "legacy pre-2008 Serbia code, duplicate of RI",
    "YI": "defunct Serbia-and-Montenegro/Yugoslavia code, retired 2006",
    "OC": "unidentified code, no confident source found",
}
DROP_DISPUTED_UNINHABITED_NOTE = {
    c: "disputed/uninhabited/maritime catch-all, not a country" for c in
    ("EU", "CK", "MQ", "CR", "IP", "BQ", "KQ", "FQ", "DQ", "JN", "BV", "LQ", "HQ",
     "WQ", "OS", "NT", "PG", "PF")
}
DROP_TERRITORY_NOTE = {
    c: "non-UN-member dependent territory (shares parent's currency)" for c in
    ("AQ", "AV", "AA", "BD", "VI", "CJ", "KT", "CW", "FK", "FO", "FP", "GI", "GL",
     "GQ_guam", "GK", "IM", "JE", "MH", "NC", "NE_niue", "NF", "CQ", "PC",
     "RQ", "SH", "TK", "VQ", "WF", "WI")
}


def region_of(code: str) -> str:
    return REGION.get(code, "africa_mideast")


def classify(code: str, currency: str) -> dict:
    """Return {regime, currency, peg_to, peg_rate, fred_fx, td_index, label_note}."""
    if code in CFA_XAF | CFA_XOF:
        ccy = "XAF" if code in CFA_XAF else "XOF"
        return {"regime": "pegged", "currency": ccy, "peg_to": "EUR", "peg_rate": "655.957",
                "fred_fx": "DEXUSEU", "td_index": TD_INDEX.get(_iso2_of(code)),
                "label_note": f"Pegged to EUR (fixed rate, CFA franc zone)"}
    if code in DOLLARIZED:
        return {"regime": "dollarized", "currency": "USD", "peg_to": None, "peg_rate": None,
                "fred_fx": None, "td_index": TD_INDEX.get(_iso2_of(code)),
                "label_note": "Dollarized economy — no exchange rate exists"}
    if code in HARD_USD_PEG:
        rate, fred_fx = HARD_USD_PEG[code]
        return {"regime": "pegged", "currency": currency, "peg_to": "USD", "peg_rate": rate,
                "fred_fx": fred_fx, "td_index": TD_INDEX.get(_iso2_of(code)),
                "label_note": "Pegged to USD (fixed rate)"}
    if code in OTHER_PEG:
        ccy, peg_to, rate, fred_fx = OTHER_PEG[code]
        return {"regime": "pegged", "currency": ccy, "peg_to": peg_to, "peg_rate": rate,
                "fred_fx": fred_fx, "td_index": TD_INDEX.get(_iso2_of(code)),
                "label_note": f"Pegged to {peg_to} (fixed rate)"}
    fred_fx = FRED_DEX.get(currency)
    td_index = TD_INDEX.get(_iso2_of(code))
    if fred_fx or td_index:
        return {"regime": "floating", "currency": currency, "peg_to": None, "peg_rate": None,
                "fred_fx": fred_fx, "td_index": td_index, "label_note": "Own currency"}
    return {"regime": "unlinked", "currency": currency, "peg_to": None, "peg_rate": None,
            "fred_fx": None, "td_index": None,
            "label_note": "Sentiment-only — no reliable market series currently sourced"}


def _iso2_of(code: str) -> str | None:
    return CODE_NAME_ISO2.get(code, (None, None))[1]


def _write_un_member_states() -> set:
    """pycountry's full ISO list minus NON_UN_ISO2 -> data/un_member_states.csv.

    Returns the resulting UN-member iso2 set. The row count is the correctness
    check: it must land exactly on 193.
    """
    import pycountry

    all_countries = list(pycountry.countries)
    un_iso2 = {c.alpha_2 for c in all_countries} - NON_UN_ISO2
    rows = sorted(
        (c.name, c.alpha_2, c.alpha_3) for c in all_countries if c.alpha_2 in un_iso2
    )
    assert len(rows) == 193, f"UN-member derivation landed on {len(rows)}, expected 193"
    with open(UN_MEMBERS_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["un_name", "iso2", "iso3"])
        w.writerows(rows)
    return un_iso2


def _write_un_candidates(candidates: list, cov_by_code: dict) -> None:
    """§1 checkpoint artifact: coverage_sentiment.csv cross-walked to UN members."""
    import pycountry

    rows = []
    for code in candidates:
        name, iso2 = CODE_NAME_ISO2[code]
        iso3 = pycountry.countries.get(alpha_2=iso2).alpha_3 if iso2 else ""
        cov = cov_by_code.get(code, {})
        rows.append((name, iso2 or "", iso3, code,
                     cov.get("distinct_days", ""), cov.get("avg_articles_per_day", "")))
    with open(UN_CANDIDATES_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["un_name", "iso2", "iso3", "fips_gdelt_code", "distinct_days", "avg_articles_per_day"])
        w.writerows(sorted(rows))


def main() -> None:
    un_iso2 = _write_un_member_states()

    cov_rows = list(csv.DictReader(open(COVERAGE_CSV, encoding="utf-8")))
    cov_codes = {r["country_code"] for r in cov_rows}
    cov_by_code = {r["country_code"]: r for r in cov_rows}

    # §1: candidate universe = UN members reachable from real coverage, plus the
    # documented non-UN exceptions. Vatican City (VT) is a UN observer and is NOT
    # in KEPT_NON_UN_EXCEPTIONS, so it is dropped here even though it was a
    # candidate in an earlier round (see docstring).
    candidates = sorted(
        c for c in CODE_NAME_ISO2 if c in cov_codes
        and (CODE_NAME_ISO2[c][1] in un_iso2 or c in KEPT_NON_UN_EXCEPTIONS)
    )
    skipped = sorted(cov_codes - set(candidates))
    _write_un_candidates(candidates, cov_by_code)

    countries = []
    for code in candidates:
        name, iso2 = CODE_NAME_ISO2[code]
        if code == "US":
            countries.append({
                "code": "US", "id": "united_states", "label": "United States",
                "region": "north_america", "currency": "USD", "monetary_regime": "floating",
                "peg_to": None, "peg_rate": None, "fred_fx": None, "td_index": "SP500",
                "us_special": True, "label_note": "Own currency (USD is the numeraire)",
            })
            continue
        currency = CURRENCY_OVERRIDE.get(code) or (CURRENCY_OF_ISO2.get(iso2) if iso2 else None)
        cls = classify(code, currency or "")
        cid = name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("'", "").replace("-", "_")
        countries.append({
            "code": code, "id": cid, "label": name, "region": region_of(code),
            "currency": cls["currency"], "monetary_regime": cls["regime"],
            "peg_to": cls["peg_to"], "peg_rate": cls["peg_rate"],
            "fred_fx": cls["fred_fx"], "td_index": cls["td_index"],
            "label_note": cls["label_note"],
        })

    doc = {
        "regions": {
            "north_america": "North America", "europe": "Europe",
            "asia_pacific": "Asia-Pacific", "latin_america": "Latin America",
            "africa_mideast": "Africa & Middle East",
        },
        "countries": countries,
        "euro_area_members": [c["id"] for c in countries if c["currency"] == "EUR"
                              and c["id"] != "monaco" and c["id"] != "san_marino"
                              and c["id"] != "vatican_city" and c["id"] != "andorra"],
    }
    header = (
        "# GENERATED by scripts/build_country_lookup.py — see that file's docstring for\n"
        "# full sourcing/citations. Candidate universe for the coverage-driven panel;\n"
        "# scripts/profile_coverage.py TEST-FETCHES every fred_fx/td_index candidate and\n"
        "# keeps only what returns real data — nothing here is asserted to work.\n"
        f"# {len(countries)} countries generated; {len(skipped)} coverage codes intentionally\n"
        "# excluded (legacy/duplicate codes, disputed/uninhabited territories, non-UN-member\n"
        "# dependencies) — see DROP_*_NOTE dicts in this script for the documented reason\n"
        "# for each.\n\n"
    )
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True, width=1000)

    regimes = {}
    for c in countries:
        regimes[c["monetary_regime"]] = regimes.get(c["monetary_regime"], 0) + 1
    print(f"Wrote {OUT_PATH} — {len(countries)} countries.")
    print(f"Regime breakdown: {regimes}")
    print(f"Skipped {len(skipped)} coverage codes (see docstring for categories): {skipped}")


if __name__ == "__main__":
    main()
