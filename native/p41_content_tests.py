"""§385–§387 的三条 wiki 判据（真战斗，`build_session_at`）。

三条都是"内容与内核看起来都没坏、玩起来不对"的那一类，所以判据必须建**真战斗**：

1. **§385 三哨兵相位**：wiki 两个来源都说中间的从 **Beam** 起手（1+2）。
   内核按 `(round-1) % Actions.len()` 取招，所以"换序"就够 —— 这条测试钉住"真的换序了"。
2. **§386 掷骰伤害能显示**：虱子的 Bite 是 `combatantCounter("roll.bite")`。
   旧预览只认字面量 ⇒ 答 -1 ⇒ 屏幕上"攻击"后面没有数字（玩家读成 0）。
3. **§387 史莱姆老大半血分裂**：wiki：*"When its HP is at or below 50%, it will split into 2
   smaller Slimes **with its current HP**"* —— 1 只 L 酸 + 1 只 L 尖，各带**当前**血量。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '''    fn building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not() {'''
assert t.count(ANCHOR) == 1

BLOCK = '''    /// §385：三哨兵的相位是 **1+2**（中间的从 Beam 起手）。
    ///
    /// wiki.gg `Sentry`：*"In the Elite encounter, the middle Sentry instead uses Beam followed by
    /// Bolt."*；fandom `Sentry`：*"1st and 3rd sentries will always start with Bolt while the 2nd
    /// sentry will always start with Beam."*
    ///
    /// 内核的循环是 `(round - 1) % Actions.len()`（`intent.rs::select_action` B3/B4）—— **按轮次**
    /// 取，不看"上一招"。所以三个哨兵 `Actions` 一样时相位全同；修法是**把中间那只的两条换序**。
    /// 这条测试同时钉住"三只都在、且第 2 只是 Beam"。
    #[test]
    fn the_three_sentries_start_out_of_phase() {
        let session = build_session_at(7, "enc_three_sentries", 80, None, 100, 0)
            .expect("the sentry elite builds");
        // `refresh_intents` 已经跑过：`intents[slot].text` 里带 authored 动作 id。
        let texts: Vec<&str> = session
            .intents
            .iter()
            .map(|intent| intent.text.split(' ').next().unwrap_or(""))
            .collect();
        assert_eq!(texts.len(), 3, "three sentries: {texts:?}");
        assert_eq!(texts[0], "sentry.bolt", "1st starts with Bolt: {texts:?}");
        assert_eq!(texts[1], "sentry.beam", "the MIDDLE one starts with Beam: {texts:?}");
        assert_eq!(texts[2], "sentry.bolt", "3rd starts with Bolt: {texts:?}");
    }

    /// §386：**掷骰伤害的意图预览**要给真值，不是 -1（玩家看到的"攻击 0"）。
    ///
    /// 虱子的 Bite 伤害是 `combatantCounter("roll.bite")`（开战掷 5–7，A2 起 6–8）。
    /// 旧 `program_damage` 只认 `const` ⇒ 整个意图答 `-1`。修法：预览带状态求值。
    ///
    /// 判据两侧都写：**A0 落在 5..=7**，且与战斗员身上那个计数器**相等**（不是中位数）。
    #[test]
    fn the_intent_preview_reads_rolled_damage() {
        let session = build_session_at(7, "enc_three_louses", 80, None, 100, 0)
            .expect("the louse fight builds");
        let mut checked = 0;
        for (slot, intent) in session.intents.iter().enumerate() {
            let Some(raw) = session.enemy_roster().get(slot) else {
                continue;
            };
            let Ok(id) = rd_core::state::CombatantId::new(raw.as_str()) else {
                continue;
            };
            let Some(combatant) = session.state.combatant(&id) else {
                continue;
            };
            let bite = combatant
                .counters()
                .iter()
                .find(|counter| counter.key.as_str() == "roll.bite")
                .map(|counter| counter.value);
            let Some(bite) = bite else { continue };
            assert!(
                (5..=7).contains(&bite),
                "A0 louse bite is rolled 5-7 (wiki), got {bite}"
            );
            // 这一回合可能是 Spit Web（非攻击，`damage == -1` 是**对的**）；只在攻击招上比。
            if intent.text.contains("Attack") {
                assert_eq!(
                    intent.damage, bite,
                    "the preview must show the rolled value ({bite}), not -1/0: {}",
                    intent.text
                );
                checked += 1;
            }
        }
        assert!(checked > 0, "at least one louse must open with Bite");
    }

    /// §387：史莱姆老大在**半血**分裂成 1 只 L 酸 + 1 只 L 尖，各带**当前**血量。
    ///
    /// wiki.gg `Slime Boss`：*"When its HP is at or below 50%, it will split into 2 smaller Slimes
    /// with its current HP."* / *"Split — Disappears and spawns 1 Acid Slime (L) and 1 Spike Slime
    /// (L) with its current HP."*
    ///
    /// 旧内容有三处不对（§387 的正文）：阈值 10 血、召唤两只**中等**史莱姆固定 10 血、
    /// 外加一条"半血改打 slam"的规则把分裂挡掉了。
    ///
    /// 判据：把 Boss 打到 50% 以下 ⇒ 它**消失**，场上出现 `acid_slime_l` 与 `spike_slime_l`，
    /// 两者的当前血量**都等于**分裂前那一刻 Boss 的血量。
    #[test]
    fn the_slime_boss_splits_into_two_large_slimes_at_half_health() {
        let mut session = build_session_at(7, "enc_slime_boss", 80, None, 100, 0)
            .expect("the slime boss builds");
        let boss = rd_core::state::CombatantId::new("slime_boss").expect("id");
        let max = session
            .state
            .combatant(&boss)
            .expect("the boss is in the fight")
            .health_max;
        // 打到 50% 以下（`phase_split` 是 `DamageTaken` 触发器）。
        let target = max / 2 - 1;
        session
            .state
            .combatant_mut(&boss)
            .expect("mutable boss")
            .health_current = target;
        // 触发一次伤害：直接派发 1 点（走触发器链）。
        session.state.enqueue_effect(rd_core::state::EffectRequest::DealDamage {
            target: Some(boss.clone()),
            amount: 1,
            ignores_block: true,
            source: Some(rd_core::state::CombatantId::new("hero").expect("hero")),
        });
        session.state.drain_effects();
        let mut acid = None;
        let mut spike = None;
        for combatant in session.state.combatants() {
            let raw = combatant.id.as_str();
            let definition = raw.split('#').next().unwrap_or(raw);
            if definition == "acid_slime_l" {
                acid = Some(combatant.health_current);
            }
            if definition == "spike_slime_l" {
                spike = Some(combatant.health_current);
            }
        }
        let expected = target - 1; // 扣掉那 1 点伤害
        assert_eq!(
            acid,
            Some(expected),
            "1 Acid Slime (L) with the boss's current HP ({expected})"
        );
        assert_eq!(
            spike,
            Some(expected),
            "1 Spike Slime (L) with the boss's current HP ({expected})"
        );
    }

    fn building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not() {'''

t = t.replace(ANCHOR, BLOCK)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('三条测试已加')
