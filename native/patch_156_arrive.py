"""§156: a tiny `arrive_at_a_fight` helper for the potion test.

Walking into a fight had three subtle rules (settle what you stand on, only walk from a settled node,
pick a *combat* neighbour), and the first version of the potion test got them wrong and failed with
`NodeNotSettled` at floor 1. One helper, used by the test, instead of a fourth copy of the loop.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

ANCHOR = "    fn play_to_the_end() {"

HELPER = '''    /// Walk until a **fight is on** and return `true` (or `false` if the map runs out).
    ///
    /// The three rules it encodes: settle whatever you are standing on, walk only from a settled node,
    /// and prefer a combat neighbour. `port-plan.md` §156 -- the first version of the potion test
    /// re-derived this and got it wrong (`NodeNotSettled` at floor 1).
    fn arrive_at_a_fight() -> bool {
        for _ in 0..24 {
            settle_here();
            if rd_run_action_count() == 0 {
                return false;
            }
            let mut combat = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node_kind(node) == 1 {
                    combat = action;
                    break;
                }
            }
            let chosen = if combat >= 0 { combat } else { 0 };
            if rd_run_step(chosen) != 0 {
                return false;
            }
            if rd_run_node_kind() == 1
                && rd_run_begin_node() == 0
                && rd_run_fight_begin() == 0
            {
                return true;
            }
        }
        false
    }

    fn play_to_the_end() {'''

if "fn arrive_at_a_fight" in source:
    print("helper already present")
else:
    at = source.find(ANCHOR)
    if at < 0:
        raise SystemExit("play_to_the_end anchor missing")
    source = source[:at] + HELPER + source[at + len(ANCHOR) :]
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("arrive_at_a_fight inserted")

# use it in the potion test
with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

START = "        // Walk to the first fight and start it."
END = "        assert!(started, \"never reached a fight to use the potion in\");"
start = source.find(START)
end = source.find(END)
if start < 0 or end < 0:
    raise SystemExit("potion prologue not found")
source = source[:start] + "        let started = arrive_at_a_fight();\n" + source[end + len(END) :]
with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("potion test uses the helper")
