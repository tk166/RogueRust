"""§277 判据：组合槽**真的**是从候选里挑，而且挑中的那只在战斗里就是它。

三件事：
1. 两个槽各自的所有候选在**不同 seed** 下都出现过（否则"组合"退化成固定组合也全绿）；
2. 挑中的那只的**招式来自它自己的记录**（`select_action` 能给出选择）——
   第一版候选只写了 Id，会造出一只**没有招式**的怪，而没有任何闸门会红；
3. `MaxHealth` 来自候选（不同候选血量不同 ⇒ 换候选时血量跟着换）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
ANCHOR = '''    #[test]
    fn every_pool_encounter_builds_and_can_pick_its_first_intents() {'''

TEST = r'''    /// §277：`Exordium Thugs` / `Wildlife` 是**组合槽** —— 不同 seed 会挑到不同候选，
    /// 而且挑中的那只在战斗里就是它（招式、血量都来自它自己的记录）。
    #[test]
    fn the_composed_encounters_pick_from_their_candidates() {
        // 每个槽里可能出现的怪物（wiki 的"或"表）。
        let thugs_first = ["louse_red", "louse_green", "acid_slime_m", "spike_slime_m"];
        let thugs_second = ["slaver_red", "blue_slaver", "cultist", "looter"];

        let mut seen_first: Vec<String> = Vec::new();
        let mut seen_second: Vec<String> = Vec::new();
        let mut seen_hp: Vec<i32> = Vec::new();
        for seed in 0..64 {
            let Ok(session) = build_session_at(seed, "enc_exordium_thugs", 70, None, 0, 0) else {
                continue;
            };
            let enemies: Vec<_> = session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .collect();
            assert_eq!(
                enemies.len(),
                2,
                "seed {seed}: a composed encounter still places exactly two enemies"
            );
            let first = enemies[0].definition_id.as_str();
            let second = enemies[1].definition_id.as_str();
            assert!(
                thugs_first.contains(&first),
                "seed {seed}: the first slot picked `{first}`, which is not one of the wiki's four"
            );
            assert!(
                thugs_second.contains(&second),
                "seed {seed}: the second slot picked `{second}`, not one of the wiki's four"
            );
            // 血量必须来自**被挑中的那条候选**（不同候选不同血 ⇒ 反过来证明"用了候选的记录"）。
            seen_hp.push(enemies[0].health_max);
            if !seen_first.iter().any(|s| s == first) {
                seen_first.push(if let Some(found) = thugs_first.iter().find(|c| **c == first) {
                    (*found).to_string()
                } else {
                    String::from("?")
                });
            }
            if !seen_second.iter().any(|s| s == second) {
                seen_second.push(second.to_string());
            }
            // 挑中的那只必须**有招式**：意图层能给它选出下一步（`select_action` 走的就是
            // 它自己的记录）。候选只写 Id 的话这里会是 `None`。
            let hero = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "player")
                .expect("a hero")
                .id;
            for enemy in &enemies {
                let at = rd_core::intent::locate_enemy(session.content, session.encounter, &enemy.id)
                    .expect("locate")
                    .unwrap_or_else(|| panic!("seed {seed}: `{:?}` has no record", enemy.id));
                let choice = rd_core::intent::select_action(
                    &session.state,
                    session.content,
                    at,
                    &enemy.id,
                    1,
                )
                .unwrap_or_else(|e| panic!("seed {seed}: select_action: {e:?}"));
                assert!(
                    choice.is_some(),
                    "seed {seed}: `{:?}` picked no action -- a candidate with no record",
                    enemy.id
                );
            }
            let _ = hero;
        }
        assert!(
            seen_first.len() >= 2,
            "64 seeds produced only {:?} for the first slot -- the composition is not random",
            seen_first
        );
        assert!(
            seen_second.len() >= 2,
            "64 seeds produced only {:?} for the second slot",
            seen_second
        );
        let mut distinct_hp = seen_hp.clone();
        distinct_hp.sort_unstable();
        distinct_hp.dedup();
        assert!(
            distinct_hp.len() >= 2,
            "every seed gave the same HP {:?} -- the HP is not coming from the candidate",
            distinct_hp
        );
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_composed_encounters_pick_from_their_candidates' not in src
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TEST + ANCHOR))
    print('§277 test appended')


main()
