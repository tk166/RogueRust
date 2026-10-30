"""§153: the Gremlin Gang belongs to act 1, not act 2.

While making the pool pick honour `Weight`, the act-2 test started failing with
`fat_gremlin,sneaky_gremlin,gremlin_wizard`: the gang sat in `Weak2` (act 2), where it does not
belong -- the wiki lists the Gremlin Gang as an **act-1** encounter, and act 2 already has its own
(setting aside that three gremlins in act 2 is a content lie a player would notice).

So: move it to `Weak` and re-spread the weights so they still sum to 100 (the content gate checks
that for `Weak`).
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

WEAK = [
    ("enc_cultist", 15),
    ("enc_jaw_worm", 14),
    ("enc_small_slimes", 14),
    ("enc_louse", 14),
    ("enc_fungi_beast", 14),
    ("enc_slaver_red", 14),
    ("enc_gremlin_gang", 15),
]

tables = document["EncounterTables"]
tables["Weak"] = [{"Id": encounter, "Weight": weight} for encounter, weight in WEAK]
tables["Weak2"] = [
    row for row in tables["Weak2"] if row["Id"] != "enc_gremlin_gang"
]
tables["Weak3"] = [
    # §153: `enc_spire_growth` had no weight at all -- with the pick honouring weights, a row
    # without one would read as 0 and never appear. Give it the same weight as its neighbours.
    dict(row, Weight=row.get("Weight") or 33) for row in tables["Weak3"]
]

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("Weak :", [(row["Id"], row["Weight"]) for row in tables["Weak"]],
      "sum", sum(row["Weight"] for row in tables["Weak"]))
print("Weak2:", [row["Id"] for row in tables["Weak2"]])
print("Weak3:", [(row["Id"], row["Weight"]) for row in tables["Weak3"]])
