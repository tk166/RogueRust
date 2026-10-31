"""rd-wasm: the potion-vocabulary tripwire (§161.3).

`rd_env_use_potion` decides what a potion does; `rd_run_potion_effect` decides whether the page
offers a target picker. Two readers of one vocabulary -- and adding `choice_hand_exhaust` to the
first and not the second produced a potion the kernel drinks while the page calls it "0 = unknown",
with nothing red.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// §161.3: the two potions whose effect is a **question**, driven end to end."""

TEST = '''    /// §161.3: **every** `POT` row must classify as a known effect.
    ///
    /// Two readers share one vocabulary: `rd_env_use_potion`'s `match` decides what a potion does,
    /// and `rd_run_potion_effect` decides whether the page offers a target picker. Adding
    /// `choice_hand_exhaust` to the first and forgetting the second produced a potion the kernel
    /// drinks happily while the page classifies it as `0 = unknown` -- and **nothing went red**,
    /// because the page's `=== 1` test simply took the other branch. Not a hypothetical: that is
    /// exactly what this section shipped into until this test was written.
    ///
    /// Walking the **whole table** is the point. A test that only checks "elixir is known" would be
    /// the same per-atom list that just failed.
    #[test]
    fn every_potion_in_the_table_classifies_as_known() {
        test_run(11, 80, 80, &["strike"; 10]);
        let image = content();
        let mut checked = 0usize;
        for index in 0..image.potion_count() {
            let Some(potion) = image.potion(index) else {
                continue;
            };
            // The belt holds three, so the table is walked one bottle at a time.
            {
                let session = run_slot().as_mut().expect("a session");
                while !session.state.potions().is_empty() {
                    session.state.drop_potion(0).expect("dropping an empty slot");
                }
                session.state.push_potion(potion.id).expect("an empty belt takes one");
            }
            let kind = rd_run_potion_effect(0);
            assert!(
                kind != 0,
                "`{}` ({}) classifies as UNKNOWN -- the page would call a working potion broken",
                potion.id,
                potion.effect
            );
            assert!(kind == 1 || kind == 2 || kind == 3, "`{}` -> {kind}", potion.id);
            checked += 1;
        }
        assert_eq!(
            checked,
            image.potion_count(),
            "every POT row must be walked, not a sample"
        );

        // "Known" is not enough for the two new atoms: they act on the **hand**, so arming the
        // enemy picker for them is a wrong branch that `kind != 0` would happily accept.
        for id in ["elixir", "gamblers_brew"] {
            {
                let session = run_slot().as_mut().expect("a session");
                while !session.state.potions().is_empty() {
                    session.state.drop_potion(0).expect("dropping an empty slot");
                }
                session.state.push_potion(id).expect("an empty belt takes one");
            }
            assert_eq!(
                rd_run_potion_effect(0),
                2,
                "`{id}` acts on the hand, so it needs no enemy target"
            );
        }
    }

    /// §161.3: the two potions whose effect is a **question**, driven end to end.'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn every_potion_in_the_table_classifies_as_known" not in text, "already inserted"
    text = text.replace(ANCHOR, TEST)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("run.rs: potion vocabulary tripwire")


if __name__ == "__main__":
    main()
