"""§214 tests: Spiker's two constraints and Spire Growth's "Smash instead" clause."""
import io

P = 'kernel/rd-wasm/src/lib.rs'
text = io.open(P, encoding='utf-8').read()

anchor = """    /// §213：`Hex`"""
new = '''    /// §214：Spiker —— `Attack` 不能连两次；`Buff Thorns` **最多 6 次**，之后只能 `Attack`。
    ///
    /// wiki `Shapes#Spiker`: "Cannot use Attack twice in a row. Cannot use Buff Thorns once it has
    /// been used 6 times and will instead using Attack."
    ///
    /// 三段判据：①上次是 Attack ⇒ 这次只能是 Buff Thorns；②`thorns_buffs` 到 6 ⇒ 只能 Attack
    /// （哪怕上次也是 Attack —— 两条规则同时许可是不可能的，所以"次数上限"必须**压过**"不能连两次"）；
    /// ③没约束时两招都出得来（50/50 的另一半）。
    #[test]
    fn spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_spiker", rd_core::content::EK_ENCOUNTER)
                .expect("enc_spiker")
                .index,
        );
        let ask = |last: i32, buffs: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_spiker", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("spiker");
            for (key, value) in [("last_move", last), ("thorns_buffs", buffs)] {
                let _ = session
                    .state
                    .combatant_mut(&id)
                    .expect("spiker")
                    .set_counter(rd_core::state::CounterId::new(key).expect("counter"), value);
            }
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("the spiker is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &id, 3)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        for seed in 0..40 {
            assert_eq!(ask(1, 0, seed), "spiker.spike", "no Attack twice in a row");
            assert_eq!(
                ask(1, 6, seed),
                "spiker.cut",
                "after six Buff Thorns it must Attack, even though it also attacked last turn"
            );
        }
        let mut free = std::collections::BTreeSet::new();
        for seed in 0..60 {
            free.insert(ask(2, 0, seed));
        }
        assert_eq!(
            free,
            ["spiker.cut".to_string(), "spiker.spike".to_string()]
                .into_iter()
                .collect::<std::collections::BTreeSet<_>>(),
            "with no constraint both moves are available"
        );
        take_session();
    }

    /// §214：Spire Growth —— 上回合 `Constrict` **或** 玩家已 Constricted ⇒ 必 `Smash`。
    ///
    /// wiki: "If Constrict was used last turn or the player already has Constricted, it uses Smash
    /// instead." 两半分开测，因为它们走的是**两条不同的条件**（`last_move` 与 `opponentHasStatus`）。
    #[test]
    fn spire_growth_smashes_instead_of_choosing() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_spire_growth", rd_core::content::EK_ENCOUNTER)
                .expect("enc_spire_growth")
                .index,
        );
        let ask = |last: i32, constricted: bool, seed: i32| -> String {
            let session = build_session_at(seed, "enc_spire_growth", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("spire_growth");
            let _ = session
                .state
                .combatant_mut(&id)
                .expect("spire growth")
                .set_counter(rd_core::state::CounterId::new("last_move").expect("counter"), last);
            if constricted {
                session
                    .state
                    .combatant_mut(&cid_in("hero"))
                    .expect("hero")
                    .push_status(
                        rd_core::state::StatusInstance::new(
                            rd_core::state::StatusInstanceId::new("st_con").expect("id"),
                            rd_core::state::StatusDefinitionId::new("standard.constricted").expect("id"),
                            rd_core::state::StatusPolarity::Debuff,
                        )
                        .with_stacks(10),
                    )
                    .expect("push");
            }
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("the spire growth is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &id, 4)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        for seed in 0..40 {
            assert_eq!(
                ask(1, false, seed),
                "spire_growth.aggressive_heavy",
                "after Constrict it smashes"
            );
            assert_eq!(
                ask(2, true, seed),
                "spire_growth.aggressive_heavy",
                "a Constricted player gets smashed"
            );
        }
        take_session();
    }

''' + anchor
assert text.count(anchor) == 1
io.open(P, 'w', encoding='utf-8', newline='').write(text.replace(anchor, new, 1))
print("§214 tests added")
