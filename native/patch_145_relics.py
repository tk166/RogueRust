"""Add the §145 relic pool: four more relics next to `burning_blood`.

The numbers are the wiki's (Pear +10 max HP, Blood Vial +2 HP on pickup, Anchor 10 Block at combat
start, Vajra 1 Strength at combat start), because `rd_run::state::RunState::relic_effect` implements
exactly those. A relic whose effect the kernel does not implement would now be **refused when it is
granted**, so shipping one here would be a trap rather than a pool.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_145_relics.py
"""

import io
import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "contentc", "packages", "sts", "sts.roguedeck.json",
)

with io.open(SRC, encoding="utf-8") as handle:
    document = json.load(handle)

relics = document["Relics"]
existing = {relic["Id"] for relic in relics}

new_relics = [
    {"Id": "anchor", "DisplayName": "Anchor", "RunPrograms": None, "CombatRules": None},
    {"Id": "vajra", "DisplayName": "Vajra", "RunPrograms": None, "CombatRules": None},
    {"Id": "pear", "DisplayName": "Pear", "RunPrograms": None, "CombatRules": None},
    {"Id": "blood_vial", "DisplayName": "Blood Vial", "RunPrograms": None, "CombatRules": None},
]

for relic in new_relics:
    if relic["Id"] in existing:
        raise SystemExit("already patched: %s exists" % relic["Id"])
    relics.append(relic)

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("relics:", [relic["Id"] for relic in relics])
