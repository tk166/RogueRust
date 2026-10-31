"""§156: make the "a potion can be drunk in a fight" test deterministic.

It used to *hunt* for a dropped potion across up to twenty fights, collecting block/energy/fire so
both assertion arms could run. With the rarity-weighted drop (§156) the potion stream shifted and the
walk ran out of moves first -- the test was measuring luck, not the feature.

The rewrite keeps the intent (`rd_env_use_potion` works, on the pipeline, in a real fight) and drops
the luck: walk to the first fight, **push** the three potions into the belt, drink them.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    lines = handle.read().split("\n")

start = next(i for i, line in enumerate(lines) if "fn a_potion_can_be_used_in_a_fight()" in line)
# the hunting prologue ends where the "find a fight to use it in" comment begins
walk = next(i for i in range(start, len(lines)) if "Find a fight to use it in" in lines[i])

HEAD = '''    /// §156: a potion, drunk **in a real fight**, does what it says.
    ///
    /// The belt contents are pushed directly instead of hunted from drops: with the rarity-weighted
    /// drop (§156) the old version -- "walk twenty fights until block + energy + fire all show up" --
    /// was measuring the potion RNG, and it broke the moment the weights changed. The **drop** is
    /// covered by the reward tests (`roll_reward`), and this test is about drinking one.
    fn a_potion_can_be_used_in_a_fight() {
        reset(4);
        // Walk to the first fight and start it.
        let mut started = false;
        for _ in 0..20 {
            assert!(rd_run_action_count() > 0, "no fight to use the potion in");
            let mut combat = -1;
            for action in 0..rd_run_action_count() {
                let node = rd_run_action_arg(action, 0);
                if node >= 0 && node_kind(node) == 1 {
                    combat = action;
                    break;
                }
            }
            let chosen = if combat >= 0 { combat } else { 0 };
            assert_eq!(rd_run_step(chosen), 0, "walk");
            if rd_run_node_kind() == 1 {
                assert_eq!(rd_run_begin_node(), 0, "begin_node");
                assert_eq!(rd_run_fight_begin(), 0, "fight_begin: {:?}", run_error_text());
                started = true;
                break;
            }
            settle_here();
        }
        assert!(started, "never reached a fight to use the potion in");

        // The three the assertions below know how to check.
        {
            let session = run_slot().as_mut().expect("session");
            for potion in ["block_potion", "energy_potion", "fire_potion"] {
                session.state.push_potion(potion).expect("the belt holds three");
            }
        }
        let belt = rd_run_potion_count();
        assert_eq!(belt, 3, "three potions in the belt");

'''

lines = lines[:start] + HEAD.split("\n") + lines[walk:]
with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(lines))
print("potion test rewritten from line", start + 1)
