"""Fold config/regions.generated.yaml's countries into config/regions.yaml.

Uses ruamel.yaml's round-trip mode so `base_query`, `sources:`, `regions:`, and
`analysis:` keep their exact comments/formatting (the methodology constants must
never silently drift) — only `countries:` is replaced wholesale with the
generated panel, and only the `euro_area` aggregate's member list is updated to
the real set the profiler found. Two new region keys (latin_america,
africa_mideast) are added since the generated panel spans them; everything else
in `regions:` is untouched.

Adds `iso3` per country (needed by the choropleth map; the generated file
doesn't carry it) by re-deriving it from the same FIPS->ISO2 table
build_country_lookup.py already uses — no new sourcing, just reuse. Does NOT add
`gdp` (would need real per-country research; the euro-area blend already
degrades gracefully to equal-weighted without it — noted, not silently fixed).

    python scripts/merge_regions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_country_lookup import CODE_NAME_ISO2  # noqa: E402

GENERATED = ROOT / "config" / "regions.generated.yaml"
TARGET = ROOT / "config" / "regions.yaml"

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 1000
yaml.indent(mapping=2, sequence=4, offset=2)

plain_yaml = YAML(typ="safe")


def _iso3_for(fips_code: str) -> str | None:
    import pycountry

    entry = CODE_NAME_ISO2.get(fips_code)
    if not entry or not entry[1]:
        return None
    c = pycountry.countries.get(alpha_2=entry[1])
    return c.alpha_3 if c else None


def main() -> None:
    with open(TARGET, encoding="utf-8") as fh:
        current = yaml.load(fh)
    with open(GENERATED, encoding="utf-8") as fh:
        generated = plain_yaml.load(fh)

    assert current["base_query"] == generated["base_query"], "base_query mismatch — investigate before merging"

    # regions: add only the 2 new keys the panel actually spans; leave the rest untouched.
    added_regions = []
    for rid, meta in generated["regions"].items():
        if rid not in current["regions"]:
            current["regions"][rid] = CommentedMap(meta)
            added_regions.append(rid)

    # countries: replace wholesale with the generated panel + derived iso3.
    countries = []
    for c in generated["countries"]:
        fips = c.get("gdelt", {}).get("source_country")
        iso3 = _iso3_for(fips) if fips else None
        new_c = CommentedMap(c)
        new_c["iso3"] = iso3
        countries.append(new_c)
    missing_iso3 = [c["id"] for c in countries if not c["iso3"]]
    current["countries"] = countries

    # aggregates: keep the existing structure/comments, swap in the real member list.
    gen_aggs = {a["id"]: a for a in generated.get("aggregates", [])}
    for agg in current.get("aggregates", []):
        if agg["id"] in gen_aggs:
            agg["sentiment"]["members"] = gen_aggs[agg["id"]]["sentiment"]["members"]

    with open(TARGET, "w", encoding="utf-8") as fh:
        yaml.dump(current, fh)

    print(f"Merged {len(countries)} countries into {TARGET}")
    print(f"Added regions: {added_regions}")
    euro_members = next(
        (a["sentiment"]["members"] for a in current.get("aggregates", []) if a["id"] == "euro_area"), [])
    print(f"euro_area members ({len(euro_members)}): {list(euro_members)}")
    if missing_iso3:
        print(f"WARNING: {len(missing_iso3)} countries have no iso3 (won't render on the map): {missing_iso3}")


if __name__ == "__main__":
    main()
