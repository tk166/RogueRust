"""§157: the ABI side of `max_hp` (Fruit Juice) and its effect code.

`max_hp` raises the **run's** maximum (and heals by the same amount, StS's behaviour) -- it is the one
potion effect that is not about the fight, which is why it is handled with `run_slot()` rather than
`session.state`.

`rd_run_potion_effect` reports `2` (acts on the hero, no target needed), so the page does not arm its
enemy picker for it.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# ---- the effect itself -------------------------------------------------------------------------
replace_once(
    """        "combat_damage_all" => {""",
    """        // §157: Fruit Juice -- the run's maximum, not the fight's. `adjust_health` heals by the
        // same amount, which is what StS's "Gain 5 Max HP" does.
        "max_hp" => {
            let Some(run) = run_slot().as_mut() else {
                return refuse("没有在进行中的一局");
            };
            run.state.raise_max_health(amount);
            session.reobserve_after_external_change();
        }
        "combat_damage_all" => {""",
    "max_hp arm",
)

# ---- the effect code --------------------------------------------------------------------------
replace_once(
    """        "combat_block" | "combat_energy" | "combat_heal_percent" | "combat_draw" => 2,""",
    """        "combat_block" | "combat_energy" | "combat_heal_percent" | "combat_draw" | "max_hp" => 2,""",
    "effect code",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("max_hp wired")
