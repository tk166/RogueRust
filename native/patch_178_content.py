"""§178 content half: the split is `destroy self, then spawn` -- the boss is *replaced*, not duplicated.

Before: `[create, create, modify(phase_split, -1)]`. The removal was a **queued** request, so the three
hits of one turn all saw the status (see `§177`), spawning ten slimes until `MAX_COMBATANTS` was full.

After: `[destroy(self), create, create]`. `destroy` is applied **immediately** (like `create`), so the
second hit finds no bearer to collect a trigger from. The guard is structural, not a counter.

Also drops the now-pointless `modifyStatusStacks(-1)` from both statuses: there is nothing left to
remove from.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

# `sel.source` resolves to the EMPTY set for a downed combatant (reference `:130`, `IsAlive`), and
# `standard.split` hangs off `Downed` -- so it must be the reference's own answer to that:
# `sel.sourceIncludingDowned` (`CombatJson.cs:319`).
SELF = {
    "kind": "sel.sourceIncludingDowned",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}


def destroy_self():
    return {
        "kind": "node.destroyCombatant",
        "value": {"TargetSelector": SELF},
    }


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    for status_id in ("standard.split", "standard.phase_split"):
        row = next(s for s in document["Statuses"] if s["Id"] == status_id)
        root = row["Triggers"][0]["Program"]["Root"]
        # `phase_split` wraps its body in a conditional; `split` is a bare sequence.
        body = root
        if root.get("kind") == "node.conditional":
            body = root["value"]["Then"]
        children = body["value"]["Children"]
        assert not any(c.get("kind") == "node.destroyCombatant" for c in children), (
            f"{status_id} already destroys itself"
        )
        kept = [c for c in children if c.get("kind") != "node.modifyStatusStacks"]
        removed = len(children) - len(kept)
        # 0 = the status never had a guard (that was the point of the bug visit), 1 = it had the
        # queued one we are replacing. Anything else means the shape moved under us.
        assert removed <= 1, f"{status_id}: unexpected extra removals ({removed})"
        body["value"]["Children"] = [destroy_self()] + kept
        print(status_id, "->", [c["kind"] for c in body["value"]["Children"]])

    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("content split now replaces the boss")


if __name__ == "__main__":
    main()
