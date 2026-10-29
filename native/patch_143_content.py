"""Add the §143 content: one Curse card and three events that use the new vocabulary.

Written as a script rather than by hand so the JSON stays byte-shape consistent
(4-space-free, `indent=2`, keys in the file's own order) and so the change is reviewable.

Run from anywhere:  python D:\\Vibe\\sts-tui\\native\\patch_143_content.py
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

cards = document["Cards"]
if any(card["Id"] == "injury" for card in cards):
    raise SystemExit("already patched: injury exists")

slimed = next(card for card in cards if card["Id"] == "slimed")
injury = json.loads(json.dumps(slimed))
injury["Id"] = "injury"
injury["NameKey"] = "Injury"
injury["DescriptionKey"] = "Unplayable."
injury["Tags"] = [{"value": "curse"}, {"value": "unplayable"}, {"value": "junk"}]
injury["Rarity"] = "Curse"
cards.append(injury)

rooms = document["UnknownRooms"]
existing = {room["Id"] for room in rooms}


def event(event_id, name, description, label0, effect0, amount0, label1, effect1, amount1=0):
    return {
        "Id": event_id,
        "NameKey": name,
        "DescriptionKey": description,
        "Label0": label0,
        "Effect0": effect0,
        "Amount0": amount0,
        "Label1": label1,
        "Effect1": effect1,
        "Amount1": amount1,
    }


new_events = [
    # StS's "Ancient Writing": the whole point is upgrading a card you chose.
    event(
        "ancient_writing",
        "Ancient Writing",
        "Glyphs older than the Spire cover the wall.",
        "Study the glyphs",
        "upgrade_card",
        0,
        "Leave them be",
        "nothing",
    ),
    # StS's curses: a real cost you accept for a reason. Here the reason is the card itself.
    event(
        "forgotten_altar",
        "Forgotten Altar",
        "A stone bowl waits for an offering.",
        "Take the offering",
        "curse:injury",
        0,
        "Walk away",
        "nothing",
    ),
    # Removing a card is the third deck edit, and the one StS prices highest.
    event(
        "purification_shrine",
        "Purification Shrine",
        "Cold water runs over a stone basin.",
        "Wash a card away",
        "remove_card",
        0,
        "Leave",
        "nothing",
    ),
]

for room in new_events:
    if room["Id"] not in existing:
        rooms.append(room)

tables = document["EventTables"]
# Act 1 gets the two new rooms (it had four); act 2 and 3 each get the removal shrine so the
# new vocabulary is reachable in every act.
for entry in tables["Events"]:
    pass
tables["Events"] = [{"Id": room["Id"]} for room in tables["Events"]]
for room_id, table in (("ancient_writing", "Events"), ("forgotten_altar", "Events"),
                       ("purification_shrine", "Events2"), ("purification_shrine", "Events3")):
    if not any(entry["Id"] == room_id for entry in tables[table]):
        tables[table].append({"Id": room_id})

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("cards:", len(cards), "events:", len(rooms))
print("act1:", [entry["Id"] for entry in tables["Events"]])
print("act2:", [entry["Id"] for entry in tables["Events2"]])
print("act3:", [entry["Id"] for entry in tables["Events3"]])
