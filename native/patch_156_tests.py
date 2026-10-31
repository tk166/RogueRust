"""§156: tests for the rarity weights, and the content gate's relic-rarity rule.

The weights are a **distribution**, so the assertions are deliberately loose: a single seed cannot
prove 50/33/17, and a tight bound would be a flaky test pretending to be a statistical one. What can
be proven on one seed:

* the common band comes up more often than the rare one (the order the weights encode);
* every band that exists in the pool is reachable;
* a band with **no** entries shifts the mass instead of returning nothing (`pick_rarity` re-normalises
  over what is present -- a pool of rares yields rares, not a silent None).
"""

import io

RUN = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"
GATE = r"D:\Vibe\sts-tui\native\sts_content_check.py"

RUN_TEST = '''
    /// §156：稀有度权重**按顺序**生效，且空档不会把抽取变空。
    ///
    /// 断言是**刻意宽松**的：单个种子证明不了 50/33/17，这只是一条"权重真的用上了"的烟测。
    /// 精确分布属于统计断言，得由多次运行去说，不该由一条测试假装。
    #[test]
    fn relic_rarity_weights_favour_commons_and_shift_when_a_band_is_empty() {
        let pool = [
            PoolRelic {
                id: "common_one",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "uncommon_one",
                rarity: Rarity::Uncommon,
            },
            PoolRelic {
                id: "rare_one",
                rarity: Rarity::Rare,
            },
        ];
        let mut run = RunState::new(21, 80, 0, &DECK).expect("a run");
        let mut commons = 0;
        let mut uncommons = 0;
        let mut rares = 0;
        for _ in 0..300 {
            let picked = run
                .pick_relic(RunStream::Chest, &pool)
                .expect("a relic each time");
            match picked.as_str() {
                "common_one" => commons += 1,
                "uncommon_one" => uncommons += 1,
                "rare_one" => rares += 1,
                other => panic!("picked {other}, which is not in the pool"),
            }
        }
        assert_eq!(commons + uncommons + rares, 300);
        assert!(commons > uncommons, "common {commons} vs uncommon {uncommons}: the 50/33 order");
        assert!(
            uncommons > rares,
            "uncommon {uncommons} vs rare {rares}: the 33/17 order"
        );
        assert!(rares > 0, "the rare band must still be reachable");

        // A pool with only rares: the weights re-normalise, they do not return nothing.
        let only_rare = [PoolRelic {
            id: "rare_one",
            rarity: Rarity::Rare,
        }];
        for _ in 0..20 {
            assert_eq!(
                run.pick_relic(RunStream::Chest, &only_rare)
                    .expect("a relic")
                    .as_str(),
                "rare_one"
            );
        }

        // An empty pool is "no relic", which is what the chest treats as an empty chest.
        assert_eq!(
            run.pick_relic(RunStream::Chest, &[]).expect("no relic").as_str(),
            "",
            "an empty pool yields the empty id, not an error"
        );
    }
'''

with io.open(RUN, encoding="utf-8") as handle:
    source = handle.read()
if "fn relic_rarity_weights_favour_commons" in source:
    print("weights test already present")
else:
    anchor = "    /// §155：**精英和 Boss 给遗物，普通怪不给**"
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("rd-run anchor missing")
    source = source[:at] + RUN_TEST.strip("\n") + "\n\n" + source[at:]
    with io.open(RUN, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("weights test inserted")

GATE_RULE = '''

RELAPSE_RARITIES = ("Common", "Uncommon", "Rare")


def check_relic_rarities(doc):
    """§156: every relic declares a rarity the drop weights know about.

    The weights are `Common 50 / Uncommon 33 / Rare 17`; a relic whose `Rarity` is missing or spelled
    differently is silently skipped by the pool reader in `rd-wasm` (`Rarity::from_name` returns
    `None`), so it would simply **never drop** -- a relic that exists and cannot be found is worse
    than one that is absent.
    """
    print("[6f] relic rarities (port-plan.md §156)")
    relics = doc.get("Relics") or []
    missing = [relic.get("Id") for relic in relics if relic.get("Rarity") not in RELAPSE_RARITIES]
    if missing:
        fail("Relics.rarity", "no usable Rarity on %s" % (missing,))
    counts = {}
    for relic in relics:
        counts[relic["Rarity"]] = counts.get(relic["Rarity"], 0) + 1
    for rarity in RELAPSE_RARITIES:
        if counts.get(rarity, 0) == 0:
            fail("Relics.rarity", "no %s relic: the weight band would be empty" % rarity)
    ok("relic rarities", "%d relics over %s" % (len(relics), sorted(counts.items())))
'''

with io.open(GATE, encoding="utf-8") as handle:
    gate = handle.read()

if "def check_relic_rarities" in gate:
    print("gate rule already present")
else:
    anchor = "def check_card_keywords(doc):"
    at = gate.find(anchor)
    if at < 0:
        raise SystemExit("gate anchor missing")
    gate = gate[:at] + GATE_RULE.strip("\n") + "\n\n\n" + gate[at:]
    gate = gate.replace("    check_upgrades(doc)", "    check_upgrades(doc)\n    check_relic_rarities(doc)", 1)
    with io.open(GATE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(gate)
    print("gate rule inserted")
