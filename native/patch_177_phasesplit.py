"""§177: `standard.phase_split` fired more than once, and the combatant container filled up.

Found by the new diagnostics: `hostFailure: Exec(Capacity(Full(Combatants)))` on a Slime Boss fight.

The status is a `DamageTaken` trigger whose program is `[create, create, modify(-1)]` -- correct in
spirit (it takes its own stack away so it only splits once) but the removal is **last**, and every
effect in a program is a **queued request** (§173 taught this: a program cannot see its own write land).
So while the boss sits at `<= 10` HP, each damage instance of the same turn re-enters the trigger before
the `-1` has been applied: 3 hits -> 3 splits -> 6 new combatants -> `MAX_COMBATANTS` (12) -> the
fight throws `Capacity(Full(Combatants))` and the run freezes.

Fix: bump the removal to the **front**. Then the first thing the drain applies is "this status is
gone", so the next damage instance in the same turn finds nothing to fire.

`docs/port-plan.md` §177 has the reproduction: a kernel test that hits the boss three times while it
is at 8 HP and asserts exactly two combatants were created.
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

row = next(status for status in document["Statuses"] if status["Id"] == "standard.phase_split")
root = row["Triggers"][0]["Program"]["Root"]
children = root["value"]["Then"]["value"]["Children"]

removal = [child for child in children
           if child.get("kind") == "node.modifyStatusStacks"
           and child["value"].get("StatusDefinitionId", {}).get("value") == "standard.phase_split"]
assert len(removal) == 1, f"expected exactly one self-removal, found {len(removal)}"
others = [child for child in children if child is not removal[0]]
root["value"]["Then"]["value"]["Children"] = removal + others

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("phase_split removes itself FIRST:",
      [child["kind"] for child in root["value"]["Then"]["value"]["Children"]])
