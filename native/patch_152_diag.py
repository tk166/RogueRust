"""Move the §152 diagnostic helpers out of `impl Session` and into module scope.

They are free functions (`fn step_cause_text(...) -> &'static str`), so putting them inside an
`impl` block was wrong from the start -- and shell-based re-indentation mangled the block instead of
fixing it. This script is the reliable version: brace-counted removal, then append at module scope
just before the `impl Session` block, and fix the `&Problem`/`Problem` comparison while it is here.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\lib.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

HEAD_DOC = "A step whose error the shell swallowed, named by family (§152)."


def cut_function(text, signature):
    """Remove one `fn` (with its doc comment) using brace counting."""
    at = text.find(signature)
    if at < 0:
        return text, False
    # walk back over the doc comment lines
    start = text.rfind("\n", 0, at) + 1
    while True:
        previous = text.rfind("\n", 0, start - 1) + 1
        line = text[previous:start].strip()
        if line.startswith("///") or line.startswith("//") or line == "":
            start = previous
            if previous == 0:
                break
            continue
        break
    depth = 0
    opened = False
    for index in range(at, len(text)):
        if text[index] == "{":
            depth += 1
            opened = True
        elif text[index] == "}":
            depth -= 1
            if opened and depth == 0:
                return text[:start] + text[index + 2 :], True
    return text, False


for signature in ("fn step_cause_text(", "fn capacity_problem_text("):
    source, removed = cut_function(source, signature)
    print(("removed " if removed else "absent  ") + signature)

HELPERS = '''/// A step whose error the shell swallowed, named by family (§152).
fn step_cause_text(cause: &str) -> &'static str {
    match cause {
        "Script" => "StepThrew(Script)",
        "Exec" => "StepThrew(Exec)",
        "Turn" => "StepThrew(Turn)",
        "Other" => "StepThrew(Other)",
        _ => "StepThrew",
    }
}

/// `StepThrew(Capacity)` plus **which** container filled up.
///
/// The names come from `state::Container::name_of` (one table, in the kernel); this function only
/// turns one into a `&'static str`, because `Session::problems` is a `Vec<&'static str>` and cannot
/// hold a formatted string.
fn capacity_problem_text(container: &str) -> &'static str {
    match container {
        "TurnOrder" => "StepThrew(Capacity:TurnOrder)",
        "Combatants" => "StepThrew(Capacity:Combatants)",
        "CardZones" => "StepThrew(Capacity:CardZones)",
        "CardInstances" => "StepThrew(Capacity:CardInstances)",
        "CardsInZone" => "StepThrew(Capacity:CardsInZone)",
        "GlobalStatuses" => "StepThrew(Capacity:GlobalStatuses)",
        "Statuses" => "StepThrew(Capacity:Statuses)",
        "Resources" => "StepThrew(Capacity:Resources)",
        "DefensivePools" => "StepThrew(Capacity:DefensivePools)",
        "Counters" => "StepThrew(Capacity:Counters)",
        "Tags" => "StepThrew(Capacity:Tags)",
        "Marks" => "StepThrew(Capacity:Marks)",
        "MarkCounters" => "StepThrew(Capacity:MarkCounters)",
        "TemporaryRules" => "StepThrew(Capacity:TemporaryRules)",
        "PendingEffects" => "StepThrew(Capacity:PendingEffects)",
        "PendingEffectChains" => "StepThrew(Capacity:PendingEffectChains)",
        "PendingEffectOwners" => "StepThrew(Capacity:PendingEffectOwners)",
        "PendingEvents" => "StepThrew(Capacity:PendingEvents)",
        "PendingEventChains" => "StepThrew(Capacity:PendingEventChains)",
        "PendingContinuations" => "StepThrew(Capacity:PendingContinuations)",
        "Chains" => "StepThrew(Capacity:Chains)",
        "EventIdList" => "StepThrew(Capacity:EventIdList)",
        "ProgramFrames" => "StepThrew(Capacity:ProgramFrames)",
        "ProgramNodeSlots" => "StepThrew(Capacity:ProgramNodeSlots)",
        "ProgramLoops" => "StepThrew(Capacity:ProgramLoops)",
        _ => "StepThrew(Capacity)",
    }
}

'''

anchor = "impl Session {"
if anchor not in source:
    raise SystemExit("impl Session missing")
source = source.replace(anchor, HELPERS + anchor, 1)

# `problem` comes from `problems_of`, which yields `&Problem`.
source = source.replace("problem == rd_core::battle::Problem::StepThrew",
                        "*problem == rd_core::battle::Problem::StepThrew")

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("helpers placed at module scope")
