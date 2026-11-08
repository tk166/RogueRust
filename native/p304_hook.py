"""§304 开战问句：`gambling_chip` + `toolbox`。

两件遗物都是"**开战那一刻**问一句"，句子形态早已存在（`PendingChoice`）：
* `gambling_chip` = 现成的 `DiscardThenDraw`（Gambler's Brew 那条），`min = 0`（wiki: "any number"）；
* `toolbox` = 现成的 `Offered`（Attack/Skill Potion 那条），但落手牌**按印刷价**（`ToHandPrinted`）。

## 时点：第 1 回合**开始之后**

两件遗物都发生在"起手牌已经抽好"之后（`gambling_chip` 弃的是起手牌；`toolbox` 加的是
起手牌之外的一张）。所以钩子挂在 `start_first_turn` + `apply_combat_bonus_block` **之后**、
提交点的 `reobserve` **之前** —— 页面读到的第一份观察里就已经带着待决问句。

## 两件同时持有：一个位掩码，按固定顺序问

内核的 `begin_choice` 拒绝嵌套（"已经有问句挂着"）。所以两件同时在身上时不能同时问。
`RunSession.open_choices` 是一个**位掩码**：`fight_begin` 时按遗物算出来，每问出一个就清一位；
`rd_env_choice_confirm` 成功后调 `ask_next_open_choice`，于是第二个问句在该答完之后才出现。

⚠️ 掩码是"欠着还没问的"，不是"一共几次"：`ask_next_open_choice` 在**已经有问句挂着**时
直接返回（不清位），所以"谁来问"永远只有一个来源。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
LIB = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① rd-run：两个变体 + 表项 + 常量
    patch(STATE, '''    /// §303：`wing_boots` —— 地图上可以**忽略路径**、直接选下一层的任意房间，''',
                '''    /// §304：`gambling_chip` —— 开战那一刻问"弃任意张手牌，然后抽同样多张"。
    CombatOpenDiscardThenDraw,
    /// §304：`toolbox` —— 开战那一刻问"从 `count` 张随机**无色**牌里选一张加进手牌"。
    CombatOpenOfferColorless {
        /// 给几张候选（wiki: 3）。
        count: u8,
    },
    /// §303：`wing_boots` —— 地图上可以**忽略路径**、直接选下一层的任意房间，''')

    patch(STATE, '''/// §303：`wing_boots` —— "select any room on the next floor … a maximum of **3** times"。''',
                '''/// §304：`toolbox` —— "At the start of each combat, choose 1 of **3** random Colorless cards"。
pub const TOOLBOX_OFFER: u8 = 3;
/// §303：`wing_boots` —— "select any room on the next floor … a maximum of **3** times"。''')

    patch(STATE, '''            // §303：`wing_boots` —— 运行层的地图规则（没有内容状态）。''',
                '''            // §304：两件"开战问一句"的遗物（问句在 `rd-wasm` 发起，内核只认形态）。
            "gambling_chip" => Some(RelicEffect::CombatOpenDiscardThenDraw),
            "toolbox" => Some(RelicEffect::CombatOpenOfferColorless {
                count: TOOLBOX_OFFER,
            }),
            // §303：`wing_boots` —— 运行层的地图规则（没有内容状态）。''')

    # ── ② rd-run：访问器（"欠着哪些问句"）
    patch(STATE, '''    /// §303：`wing_boots` 还能飞几次（没有遗物时恒 0）。''',
                '''    /// §304：这一场开战时要问玩家哪些话 —— 位掩码（`0b01` = `gambling_chip`，
    /// `0b10` = `toolbox`）与候选张数。
    ///
    /// 为什么是位掩码而不是 `Option<…>`：**两件可以同时在身上**，而内核一次只允许一个问题。
    /// 顺序固定（低位先问），所以同一颗种子的问句序列是确定的。
    #[must_use]
    pub fn combat_open_choices(&self) -> (u8, u8) {
        let mut mask = 0u8;
        if matches!(
            self.first_relic_effect_of(RelicEffect::CombatOpenDiscardThenDraw),
            Some(RelicEffect::CombatOpenDiscardThenDraw)
        ) {
            mask |= COMBAT_OPEN_GAMBLING_CHIP;
        }
        let mut offer = 0u8;
        if let Some(RelicEffect::CombatOpenOfferColorless { count }) =
            self.first_relic_effect_of(RelicEffect::CombatOpenOfferColorless {
                count: TOOLBOX_OFFER,
            })
        {
            mask |= COMBAT_OPEN_TOOLBOX;
            offer = count;
        }
        (mask, offer)
    }

    /// §303：`wing_boots` 还能飞几次（没有遗物时恒 0）。''')

    patch(STATE, '''/// §304：`toolbox` —— "At the start of each combat, choose 1 of **3** random Colorless cards"。''',
                '''/// §304：`toolbox` —— "At the start of each combat, choose 1 of **3** random Colorless cards"。
/// §304：`combat_open_choices` 的两位（顺序 = 问句顺序）。
pub const COMBAT_OPEN_GAMBLING_CHIP: u8 = 1 << 0;
pub const COMBAT_OPEN_TOOLBOX: u8 = 1 << 1;''')

    # ── ③ 三处 match 清单
    patch(STATE, '''            // §303：`wing_boots` 只改地图的 `reachable()`，不参与任何"拿到那一刻"的效果。
            | RelicEffect::WingBoots { .. }''',
                '''            // §303：`wing_boots` 只改地图的 `reachable()`，不参与任何"拿到那一刻"的效果。
            | RelicEffect::WingBoots { .. }
            // §304：两件"开战问一句"的遗物也都不在"拿到那一刻"里。
            | RelicEffect::CombatOpenDiscardThenDraw
            | RelicEffect::CombatOpenOfferColorless { .. }''')

    s = io.open(STATE, encoding='utf-8').read()
    lines = s.split('\n')
    targets = [i for i, line in enumerate(lines)
               if line.strip() == '| RelicEffect::WingBoots { .. },']
    assert len(targets) == 2, len(targets)
    for i in reversed(targets):
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = lines[i].rstrip()[:-1]
        lines[i + 1:i + 1] = [f'{indent}// §304：两件"开战问一句"的遗物同样不属于这两个钩子。',
                             f'{indent}| RelicEffect::CombatOpenDiscardThenDraw',
                             f'{indent}| RelicEffect::CombatOpenOfferColorless {{ .. }},']
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))

    # ── ④ RunSession 字段
    patch(RUN, '''struct RunSession {''', '''/// §304：开战时欠着的问句（位掩码，`rd_run` 的 `COMBAT_OPEN_*`）。
///
/// 不是"一共几次"，是"**还没问出口**的那几位"：`ask_next_open_choice` 每问一个清一位，
/// 而"已经有问句挂着"时它一位都不清（谁来问只有一个来源）。
#[derive(Default)]
struct OpenChoices {
    mask: u8,
    /// `toolbox` 给几张候选（`0` = 没有 `toolbox`）。
    offer: u8,
}

struct RunSession {''')

    # ── ⑤ 提问函数 + 收尾函数（放在 fight_begin 之前）
    patch(RUN, '''/// §170 `P1-1`: 一次失败的 `fight_begin` 必须**什么都没改**。''',
                '''/// §304：问**下一个**欠着的问句。`Ok(true)` = 真的问了（页面会看到待决）。
///
/// 三个前置条件，一个都不能省：
/// 1. 有欠着的位（没有就是没事做）；
/// 2. 内核**现在没有**问句挂着（`begin_choice` 会拒绝嵌套，而"先挂了别人的问题"这件事
///    §261 的触发器和药水都做得到 —— 那时不清位，等它答完再来）；
/// 3. 战斗会话在（`fail_begin` 之后没有会话）。
pub(crate) fn ask_next_open_choice() -> Result<bool, std::string::String> {
    let Some(run) = run_slot().as_mut() else {
        return Ok(false);
    };
    if run.open_choices.mask == 0 {
        return Ok(false);
    }
    let Some(combat) = crate::slot() else {
        return Ok(false);
    };
    if combat.state.pending_choice().is_some() {
        return Ok(false);
    }
    let Some(hero) = combat.hero_id() else {
        return Ok(false);
    };
    if run.open_choices.mask & rd_run::state::COMBAT_OPEN_GAMBLING_CHIP != 0 {
        run.open_choices.mask &= !rd_run::state::COMBAT_OPEN_GAMBLING_CHIP;
        let hand = combat
            .state
            .card_zones(&hero)
            .map_or(0, |zones| zones.count(rd_core::state::CardZone::Hand));
        if hand > 0 {
            let question = rd_core::state::PendingChoice {
                chooser: hero,
                source: rd_core::state::ChoiceSource::Hand,
                // wiki: "discard **any number** of cards, then draw that many" —— 0 是合法答案，
                // 所以这个问句永远可以"什么都不选"地答完（与 Gambler's Brew 逐字同形）。
                min: 0,
                max: hand.min(u8::MAX as usize) as u8,
                then: rd_core::state::ChoiceThen::DiscardThenDraw,
                offered: rd_core::state::Bounded::new(),
                candidates: rd_core::state::Bounded::new(),
            };
            if let Err(e) = combat.state.begin_choice(question) {
                return Err(std::format!("`gambling_chip` 的问句问不出口：{e}"));
            }
            combat.choice_picks.clear();
            combat.reobserve_after_external_change();
            return Ok(true);
        }
    }
    if run.open_choices.mask & rd_run::state::COMBAT_OPEN_TOOLBOX != 0 {
        let count = usize::from(run.open_choices.offer);
        run.open_choices.mask &= !rd_run::state::COMBAT_OPEN_TOOLBOX;
        if count == 0 {
            return Ok(false);
        }
        let pool = colorless_card_pool()?;
        if pool.len() < count {
            return Err(std::format!(
                "无色牌只有 {} 张，凑不出 {count} 张候选",
                pool.len()
            ));
        }
        let Some(run) = run_slot().as_mut() else {
            return Ok(false);
        };
        let mut picked = [rd_run::state::RunId::EMPTY; 3];
        let drawn = run
            .state
            .draw_distinct(&pool, count.min(picked.len()), &mut picked)
            .map_err(|e| std::format!("从无色牌池抽候选失败：{e}"))?;
        if drawn < count {
            return Err("抽不出足够的候选牌".to_string());
        }
        let Some(combat) = crate::slot() else {
            return Ok(false);
        };
        let mut offered = rd_core::state::Bounded::new();
        for id in &picked[..drawn] {
            let definition = rd_core::state::CardDefinitionId::new(id.as_str())
                .map_err(|_| std::format!("候选牌的 id 不合法：{}", id.as_str()))?;
            offered
                .push(definition, rd_core::state::Container::ChoiceOptions)
                .map_err(|_| "候选表装不下".to_string())?;
        }
        let question = rd_core::state::PendingChoice {
            chooser: hero,
            source: rd_core::state::ChoiceSource::Offered,
            min: 1,
            max: 1,
            // §304：`ToHandPrinted` —— **按印刷价格**进手牌（与药水的 `ToHand` 不同）。
            then: rd_core::state::ChoiceThen::ToHandPrinted,
            offered,
            candidates: rd_core::state::Bounded::new(),
        };
        if let Err(e) = combat.state.begin_choice(question) {
            return Err(std::format!("`toolbox` 的问句问不出口：{e}"));
        }
        combat.choice_picks.clear();
        combat.reobserve_after_external_change();
        return Ok(true);
    }
    Ok(false)
}

/// §304：**内容里的无色牌池**（`CARD.Tags` 含 `colorless`、跳过 `+` 行）。
///
/// 与 `choice_offered` 那个药水池同一套规矩，只有一条不同：**不排除 X 费牌**。
/// 药水要给"本回合 0 费"，那要靠每副本绝对价，X 费牌对它不可见（§246）；
/// `toolbox` 一个字都不写价格，所以 X 费牌在这里是合法的候选。
fn colorless_card_pool() -> Result<Vec<rd_run::state::PoolCard<'static>>, std::string::String> {
    let image = content();
    let mut pool: Vec<rd_run::state::PoolCard<'static>> = Vec::new();
    let mut index = 0u32;
    while let Some(row) = image.card(index) {
        index += 1;
        let Some(id) = image.string(row.id()) else {
            continue;
        };
        if id.ends_with('+') {
            continue;
        }
        if image.card_has_tag(id, "colorless") != Some(true) {
            continue;
        }
        let Some(rarity) =
            rd_run::state::Rarity::from_name(image.string(row.rarity()).unwrap_or(""))
        else {
            return Err(std::format!("`{id}` 的稀有度认不出来"));
        };
        pool.push(rd_run::state::PoolCard {
            id,
            rarity,
            kind: rd_run::state::CardKind::Other,
            upgraded: None,
        });
    }
    Ok(pool)
}

/// §304：一个问句答完之后接着问下一句（`rd_env_choice_confirm` 的两条成功分支都走这里）。
///
/// 失败**不**回滚已经答完的那一句：那句是真的答完了，下一句问不出口是一条内容/容量错误，
/// 记进错误缓冲（页面会显示），而不是把玩家的选择吞掉。
pub(crate) fn after_choice_resolved() {
    match ask_next_open_choice() {
        Ok(true) => {}
        Ok(false) => {}
        Err(message) => {
            if let Some(combat) = crate::slot().as_mut() {
                combat.error.clear();
                combat.error.push_str(&message);
            }
        }
    }
}

/// §170 `P1-1`: 一次失败的 `fight_begin` 必须**什么都没改**。''')

    # ── ⑥ fight_begin：算掩码 + 问第一句
    patch(RUN, '''                .and_then(|()| apply_combat_bonus_block(bonus))
                .err()''',
                '''                .and_then(|()| apply_combat_bonus_block(bonus))
                .and_then(|()| {
                    // §304：两件"开战问一句"的遗物。时点是**第 1 回合已经开始之后** ——
                    // `gambling_chip` 弃的是起手牌、`toolbox` 加的是起手牌之外的一张。
                    let (mask, offer) = crate::slot()
                        .as_ref()
                        .map(|combat| combat.state.combat_open_choices())
                        .unwrap_or((0, 0));
                    let Some(session) = run_slot().as_mut() else {
                        return Ok(());
                    };
                    session.open_choices.mask = mask;
                    session.open_choices.offer = offer;
                    // 第一个问句现在就问；失败属于内容错误（池子凑不出候选等）。
                    ask_next_open_choice().map(|_| ())
                })
                .err()''')

    # ── ⑦ 初始化
    patch(RUN, '''    *run_slot() = Some(RunSession {''', '''    *run_slot() = Some(RunSession {
        open_choices: OpenChoices::default(),''')

    print('run hook wired')


main()
