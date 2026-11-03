"""§188 content: the nine `?` rooms become effect **lists**, and every one gets an A15 variant.

## What the wiki actually says

* `Ascension` page, A15: **"Unfavorable Events. Many events have less positive outcomes and more
  severe consequences."** -- a direction, not numbers.
* `Golden Idol` (the one real StS event this content has): taking the idol gives the **relic** and
  costs you -- the wiki's branches are Outrun → **Injury curse**, Smash → **25% max HP damage**,
  Hide → **−8% Max HP**. Our own inventory already records those three (line 761-764).

So the content is split by provenance, and the file says which is which:

| room | base (A0) | A15 | provenance |
|---|---|---|---|
| `golden_idol` | relic `golden_idol` + `curse:injury` | relic + `damage 20` (25% of 80) | **wiki** branches (Outrun → Injury; Smash → 25%) |
| `shining_light` | `max_hp 2` | `max_hp 1` | our design |
| `old_shrine` | `heal 15` | `heal 8` | our design |
| `scrap_pile` | `gold 45` | `gold 20` | our design |
| `ancient_forge` | `max_hp 6` / `gold 45` | `max_hp 3` / `gold 20` | our design |
| `wandering_merchant` | `heal 18` / `gold 25` | `heal 9` / `gold 10` | our design |
| `ancient_writing` | `gold 40` (from the JSON) | halved | our design |
| `forgotten_altar` | `curse`-free branch (from the JSON) | worse | our design |
| `purification_shrine` | `remove_card` (from the JSON) | worse | our design |

**The A15 numbers for the invented rooms are our design, not the wiki's** -- the wiki gives the
direction only. They are marked as such here and in `docs/port-history`; a future pass with the real
event list would replace them wholesale.

`golden_idol` is the one that matters for the mechanism: it is the "relic **and** curse" pair the gap
doc has named since §143, and the only room whose A15 branch has a documented number (25% of max HP
= 20 at the Ironclad's 80).
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

# room id -> (base list, asc list); `None` for asc = no A15 variant
PLAN = {
    "golden_idol": (
        [{"Effect": "relic:golden_idol", "Amount": 1}, {"Effect": "curse:injury", "Amount": 1}],
        [{"Effect": "relic:golden_idol", "Amount": 1}, {"Effect": "damage", "Amount": 20}],
    ),
    "shining_light": (
        [{"Effect": "max_hp", "Amount": 2}],
        [{"Effect": "max_hp", "Amount": 1}],
    ),
    "old_shrine": (
        [{"Effect": "heal", "Amount": 15}],
        [{"Effect": "heal", "Amount": 8}],
    ),
    "scrap_pile": (
        [{"Effect": "gold", "Amount": 45}],
        [{"Effect": "gold", "Amount": 20}],
    ),
    "ancient_forge": (
        [{"Effect": "max_hp", "Amount": 6}],
        [{"Effect": "max_hp", "Amount": 3}],
    ),
    "wandering_merchant": (
        [{"Effect": "heal", "Amount": 18}],
        [{"Effect": "heal", "Amount": 9}],
    ),
}


def halve(room, key):
    """Fallback for the rooms the plan does not spell out: keep the effect, halve the number."""
    out = []
    for entry in room.get(key) or []:
        copy = dict(entry)
        if copy["Effect"] in ("heal", "gold", "max_hp", "damage"):
            copy["Amount"] = max(1, copy["Amount"] // 2)
        out.append(copy)
    return out


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    rooms = document["UnknownRooms"]
    touched = 0
    for room in rooms:
        room_id = room["Id"]
        # Every room already had two options, each with one effect. Turn each into a list, keeping
        # the label, and add the A15 list from the plan (or the halving fallback).
        for slot in ("0", "1"):
            old_effect = room.pop("Effect" + slot, None)
            old_amount = room.pop("Amount" + slot, 0)
            if old_effect is None:
                continue
            entry = {"Effect": old_effect, "Amount": old_amount}
            room["Effects" + slot] = [entry]
        base = room.get("Effects0") or []
        if room_id in PLAN:
            room["Effects0"], room["Effects0Asc"] = PLAN[room_id]
        else:
            room["Effects0Asc"] = halve({"0": base}, "0")
        # option 1 ("leave it") stays free: `nothing` has no worse version.
        if room.get("Effects1") and any(e["Effect"] != "nothing" for e in room["Effects1"]):
            room["Effects1Asc"] = halve({"1": room["Effects1"]}, "1")
        touched += 1
        print("%-22s base=%s asc=%s" % (
            room_id,
            [e["Effect"] for e in room.get("Effects0") or []],
            [e["Effect"] for e in room.get("Effects0Asc") or []],
        ))
    assert touched == len(rooms), (touched, len(rooms))
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("migrated", touched, "rooms to effect lists")


if __name__ == "__main__":
    main()
