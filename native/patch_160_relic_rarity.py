"""§160: the two relic rarities the review caught by checking the wiki.

* `eternal_feather` was `Rare`, the wiki's navbox and its own patch note say **Uncommon**
  ("Patch V2.0: Eternal Feather relic rarity changed from Boss -> Uncommon").
* `golden_idol` was `Rare` and therefore in the drop pool; the wiki's relic navbox lists
  `Golden Idol (Relic)` under **Event**, i.e. it is not droppable at all. It gets the new
  `Event` rarity, which `pick_relic_avoiding` filters out before the weight draw.
"""
import json
import pathlib

PATH = pathlib.Path("tools/contentc/packages/sts/sts.roguedeck.json")

FIX = {
    "eternal_feather": "Uncommon",
    "golden_idol": "Event",
}


def main():
    doc = json.loads(PATH.read_bytes().decode("utf-8"))
    for relic in doc["Relics"]:
        want = FIX.get(relic["Id"])
        if want is not None:
            print(relic["Id"], relic.get("Rarity"), "->", want)
            relic["Rarity"] = want
    PATH.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    bands = {}
    for relic in doc["Relics"]:
        bands[relic["Rarity"]] = bands.get(relic["Rarity"], 0) + 1
    print("relics", len(doc["Relics"]), bands)


if __name__ == "__main__":
    main()
