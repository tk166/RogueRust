"""§157: rewrite the potion-drop test around the **rule**, not around a rate.

It used to roll 400 rewards and assert "about 40% dropped". Two things broke that:

* the drop chance now **moves** (-10/+10), so the long-run rate is not 40% -- it is the stationary
  rate of that walk, which is a different number and not what the wiki promises;
* each iteration needs a `skip_reward` to advance the pending state, or the run stays on the first
  reward screen.

The rule is what matters: **with the chance at 100 a potion always drops, with it at 0 never**, and a
dropped potion goes onto the belt and off the table. The rate behaviour is `the_potion_chance_walks_…`.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

START = "    fn a_won_fight_drops_a_potion_and_the_belt_takes_it() {"
NEW_BODY = '''    fn a_won_fight_drops_a_potion_and_the_belt_takes_it() {
        let pool = [
            PoolPotion {
                id: "fire_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "block_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "energy_potion",
                rarity: Rarity::Uncommon,
            },
        ];
        // §157: the chance **moves** (-10/+10), so "about 40% over 400 rolls" is no longer the
        // promise -- the promise is "at 100 it always drops, at 0 it never does". The rate walk has
        // its own test (`the_potion_chance_walks_the_wikis_ten_percent`).
        let mut run = ironclad();
        run.potion_chance = 100;
        run.roll_reward(&basic_pool(), &pool, &[], FightKind::Normal)
            .expect("a reward");
        let offered = run.reward_potion().expect("at 100% it must drop").to_string();
        assert!(
            ["fire_potion", "block_potion", "energy_potion"].contains(&offered.as_str()),
            "{offered} is not in the pool"
        );
        assert_eq!(run.potion_drop_chance(), 90, "a drop moves the chance down by 10");

        // Taking it lands on the belt and consumes the offer.
        let belt_before = run.potions().len();
        run.take_potion().expect("take it");
        assert_eq!(run.potions().len(), belt_before + 1, "the potion is on the belt");
        assert_eq!(run.reward_potion(), None, "the offer is consumed");
        assert_eq!(
            run.take_potion(),
            Err(RunError::NoSuchPotion),
            "taking it twice is refused"
        );

        // At 0% nothing drops, and the chance walks back up.
        let mut run = ironclad();
        run.potion_chance = 0;
        run.roll_reward(&basic_pool(), &pool, &[], FightKind::Normal)
            .expect("a reward");
        assert_eq!(run.reward_potion(), None, "at 0% nothing drops");
        assert_eq!(run.potion_drop_chance(), 10, "a miss moves the chance up by 10");
    }
'''

start = source.find(START)
if start < 0:
    raise SystemExit("test not found")
# find the end of this function by brace counting from the opening brace after the signature
depth = 0
opened = False
end = None
for index in range(source.find("{", start), len(source)):
    if source[index] == "{":
        depth += 1
        opened = True
    elif source[index] == "}":
        depth -= 1
        if opened and depth == 0:
            end = index + 1
            break
if end is None:
    raise SystemExit("unbalanced")
source = source[:start] + NEW_BODY.rstrip("\n") + source[end:]

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("potion drop test rewritten")
