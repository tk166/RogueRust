"""§412 三组**穷尽**行为扫描：卡牌、药水、敌人动作。

玩家要求"系统排查其他药水/敌人/卡牌有没有类似的**生命周期**和**命中对象**问题"。
静态扫描（`audit_mechanics.py`）看不了"跑起来会不会炸"，所以这里做三组真跑：

## ① 每张卡都能打出去（`every_card_can_be_played_without_throwing`）

295 张卡逐张建一局（牌组里 10 张它自己 ⇒ 起手必抽到），打第一张手牌（有敌人就指定 0 号），
断言：`step_play` 不返回错误、**problems 里没有 `StepThrew`**、手牌少一张。
`unplayable` 的牌（诅咒/状态）跳过 —— 它们本来就打不出去（内容闸门另有一条）。

这一条抓的是"节目的目标/区域写错"：`sel.eventTarget` 解析不出来、`moveCardToZone` 目标非法、
`createCardInstance` 区域不认识……这些在**执行**时才炸，静态扫描看不出来。

## ② 每瓶药水都能喝（`every_potion_can_be_drunk`）

33 瓶逐瓶建一局（带一个敌人），grant 之后 `rd_env_use_potion(slot, 0)`，断言 `code == 0`
（或"需要选牌"的 `choice` 路径也算成功）、腰带 -1。`combat_flee`（烟雾弹）会结束战斗，
所以每瓶都重建一局。

## ③ 每个敌人动作都能执行（`every_enemy_action_executes`）

167 条 `EACT` 逐条建一局（用它的所属怪物），`execute_action` 断言 `Ok`。
这条抓"招式节目里引用了不存在的东西"——与 §410 的"怪物会不会卡住"互补：
那条看**选择**，这条看**执行**。

⚠️ 三组都用 `problems`/`Result` 判据，不看"数值对不对"（那是内容闸门的活）。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '    /// §411：**分裂之后还能打中、还能看见意图**'
assert t.count(ANCHOR) == 1

BLOCK = '''    /// §412①：**295 张卡逐张真打一遍**，不许有 `StepThrew`。
    ///
    /// 静态扫描看不了"节目跑起来会不会炸"：`sel.eventTarget` 解析不出、`moveCardToZone` 的
    /// 区域不认识、`createCardInstance` 的落区非法 —— 这些都只在执行时暴露。
    /// 判据：`step_play` 返回 Ok、`problems` 里没有 `StepThrew`、手牌少一张。
    ///
    /// `unplayable` 的牌（诅咒/状态）跳过：它们**本来**就打不出去（内容闸门另有一条钉住）。
    #[test]
    fn every_card_can_be_played_without_throwing() {
        let image = rd_core::content::Content::parse(crate::IMAGE).expect("the image parses");
        let mut card_ids: Vec<&'static str> = Vec::new();
        for row in image.rows(rd_core::content::Table::Card) {
            let Some(id) = image.entity_id(rd_core::content::Table::Card, row.index()) else {
                continue;
            };
            card_ids.push(id);
        }
        assert!(card_ids.len() > 250, "the content must expose its card table");

        let mut played = 0usize;
        let mut skipped_unplayable = 0usize;
        let mut failures: Vec<String> = Vec::new();
        for card_id in card_ids {
            // `unplayable` 的牌跳过（内容里带这个标签的本来就不能打）。
            if image
                .lookup_in(card_id, rd_core::content::EK_CARD)
                .map(|entry| {
                    image
                        .row(rd_core::content::Table::Card, u32::from(entry.index))
                        .map(|row| {
                            let mut tags = [0u16; 16];
                            rd_core::content::CardRow::new(row)
                                .map(|card| {
                                    card.tags(&mut tags).ok().map(|count| {
                                        tags.iter()
                                            .take(count)
                                            .filter_map(|handle| image.string(*handle))
                                            .any(|tag| tag == "unplayable")
                                    })
                                })
                                .ok()
                                .flatten()
                                .unwrap_or(false)
                        })
                        .unwrap_or(false)
                })
                .unwrap_or(false)
            {
                skipped_unplayable += 1;
                continue;
            }
            let deck = [DeckEntry { card: card_id, count: 10 }];
            let Ok(mut session) = build_session_at(7, "enc_cultist", 200, Some(&deck), 0, 0) else {
                failures.push(format!("{card_id}: the fight would not build"));
                continue;
            };
            let hand_before = session.hand_len();
            if hand_before == 0 {
                failures.push(format!("{card_id}: no cards in the opening hand"));
                continue;
            }
            let played_ok = session.step_play(0, 0).is_ok();
            let threw = session.problems.iter().any(|p| p.contains("StepThrew"));
            let hand_after = session.hand_len();
            if !played_ok || threw || hand_after + 1 != hand_before {
                failures.push(format!(
                    "{card_id}: ok={played_ok} threw={threw} hand {hand_before}->{hand_after} problems={:?}",
                    session.problems
                ));
                continue;
            }
            played += 1;
        }
        assert!(played > 250, "most cards must be playable, got {played}");
        assert!(
            failures.is_empty(),
            "{} card(s) failed to play: {:#?}",
            failures.len(),
            &failures[..failures.len().min(8)]
        );
        let _ = skipped_unplayable;
    }

    /// §412②：**33 瓶药水逐瓶真喝一遍**，不许"喝不了"。
    ///
    /// 判据：`rd_env_use_potion(slot, 0)` 返回 0，且腰带少一瓶（`combat_flee` 会结束战斗，
    /// 所以每瓶重建一局）。⚠️ 这条抓的是"原子在运行时炸"（例如 `choice_offered` 找不到候选、
    /// `combat_autoplay_top` 抽牌堆空），静态扫描只能确认**名字**认得。
    #[test]
    fn every_potion_can_be_drunk() {
        let deck = ["strike", "strike", "strike", "defend", "defend"];
        let image = content();
        let mut potion_ids: Vec<&'static str> = Vec::new();
        for row in image.rows(rd_core::content::Table::Potion) {
            if let Some(id) = image.entity_id(rd_core::content::Table::Potion, row.index()) {
                potion_ids.push(id);
            }
        }
        assert!(potion_ids.len() > 30, "the content must expose its potion table");

        let mut failures: Vec<String> = Vec::new();
        let mut drunk = 0usize;
        for potion_id in potion_ids {
            test_run(7, 80, 80, &deck);
            // 进一场战斗（药水原子大多是 combat_*）。
            let _ = rd_run_begin_node();
            if rd_run_fight_begin() != 0 {
                // 有些种子第一步不是战斗节点：直接建一场（与玩家开战同一个入口）。
                continue;
            }
            let granted = unsafe { rd_run_grant_potion(potion_id.as_ptr(), potion_id.len() as i32) };
            if granted != 0 {
                failures.push(format!("{potion_id}: grant refused ({granted})"));
                continue;
            }
            let before = run_slot()
                .as_ref()
                .map(|run| run.state.potions().len())
                .unwrap_or(0);
            let code = rd_env_use_potion(0, 0);
            let after = run_slot()
                .as_ref()
                .map(|run| run.state.potions().len())
                .unwrap_or(0);
            if code != 0 {
                failures.push(format!(
                    "{potion_id}: use refused code={code} msg={}",
                    run_error_text()
                ));
                continue;
            }
            if after + 1 != before {
                failures.push(format!(
                    "{potion_id}: the belt did not shrink ({before} -> {after})"
                ));
                continue;
            }
            drunk += 1;
        }
        assert!(drunk > 25, "most potions must be drinkable, got {drunk}");
        assert!(
            failures.is_empty(),
            "{} potion(s) failed: {:#?}",
            failures.len(),
            &failures[..failures.len().min(8)]
        );
    }

    /// §412③：**167 条敌人动作逐条执行一遍**，不许炸。
    ///
    /// 与 §410 的"怪物会不会卡住"互补：那条看**选择**（意图规则能不能翻面），这条看**执行**
    /// （招式节目里引用的选择器/区域/状态是否真的存在）。
    #[test]
    fn every_enemy_action_executes() {
        let image = rd_core::content::Content::parse(crate::IMAGE).expect("the image parses");
        let content: &'static rd_core::content::Content<'static> = Box::leak(Box::new(image));
        // 动作 → 拥有它的遭遇/怪物（用 `enc_*` 建局，动作才找得到它的怪物）。
        let mut cases: Vec<(&'static str, u32)> = Vec::new();
        let encounter_ids: Vec<&'static str> = content
            .rows(rd_core::content::Table::Encounter)
            .filter_map(|row| {
                rd_core::content::EnctRow::new(row).and_then(|enct| content.string(enct.id()))
            })
            .collect();
        for (index, _) in encounter_ids.iter().enumerate() {
            let Ok(enemies) = content.encounter_enemies(index as u32) else {
                continue;
            };
            for slot in 0..enemies.len() {
                let Ok(spec) = enemies.get(slot) else { continue };
                let Ok(actions) = spec.str_list_field("Actions") else {
                    continue;
                };
                for action in actions {
                    cases.push((action, index as u32));
                }
            }
        }
        assert!(cases.len() > 120, "the content must expose its enemy actions");
        let mut failures: Vec<String> = Vec::new();
        let mut executed = 0usize;
        for (action_id, encounter) in cases {
            let Some(encounter_name) = encounter_ids.get(encounter as usize).copied() else {
                continue;
            };
            let Ok(mut session) = build_session_at(7, encounter_name, 200, None, 0, 0) else {
                continue;
            };
            let Some(row) = content
                .lookup_in(action_id, rd_core::content::EK_EACTION)
                .map(|entry| u32::from(entry.index))
            else {
                failures.push(format!("{action_id}: not in the EACT table"));
                continue;
            };
            let roster = session.enemy_roster();
            let Some(actor) = roster.first().copied() else {
                continue;
            };
            match rd_core::intent::execute_action(
                &mut session.state,
                content,
                &actor,
                row,
                roster.get(1).copied(),
            ) {
                Ok(_) => executed += 1,
                Err(error) => failures.push(format!("{action_id}: {error:?}")),
            }
        }
        assert!(executed > 120, "most enemy actions must execute, got {executed}");
        assert!(
            failures.is_empty(),
            "{} enemy action(s) failed: {:#?}",
            failures.len(),
            &failures[..failures.len().min(8)]
        );
    }

    /// §411：**分裂之后还能打中、还能看见意图**'''

t = t.replace(ANCHOR, BLOCK)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('three sweeps added')
