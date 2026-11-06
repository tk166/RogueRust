"""§242 内核（下）：意图事实 + 掉血计数与费用阶段 + 腐化两条规则。"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


# ============================================================ expr.rs：intent.targetIntendsAttack
patch('expr.rs', [
    ('''    "intent.opponentCardsPlayed",
];''',
     '''    "intent.opponentCardsPlayed",
    // §242：**目标这回合打算攻击吗**（`Spot Weakness`）。
    //
    // 与上面两条 `intent.*` 不是一回事：那两条是**敌人选招 DSL** 里的条件（"它选招时要满足什么"），
    // 这一条是**问题本身**（"它已经选的招是不是攻击"）。实现走 `intent::select_action` ——
    // 页面显示意图用的同一个纯函数，所以"牌看到的意图"与"玩家看到的意图"不可能不一致。
    "intent.targetIntendsAttack",
];'''),
    ('''        "event.bool" => {''',
     '''        // §242: "does the chosen target intend to attack this turn" (Spot Weakness).
        //
        // 三处齐全才回答：有内容（意图表）、有目标（`sel.eventTarget`）、有遭遇（`state.encounter`）。
        // 任何一处缺 ⇒ `false` 而**不是**报错：这张牌在"没有目标"时本来就该什么都不做
        // （内容侧那条 `conditional` 就是这么用的），报错会让一张普通牌在空目标下炸掉战斗。
        // 但"有内容却说不出意图"（`ENCT` 行坏掉）是**内容 bug**，那时要响亮 —— 所以解不出来
        // 的 `Err` 走 `UnsupportedKind`。
        "intent.targetIntendsAttack" => {
            let Some(content) = ctx.content else {
                return Err(ExprError::UnsupportedKind);
            };
            let Some(target) = ctx.event_target else {
                return Ok(false);
            };
            let Ok(Some(at)) = crate::intent::locate_enemy(&content, ctx.state.encounter, &target)
            else {
                return Ok(false);
            };
            let round = ctx.state.current_round;
            match crate::intent::select_action(ctx.state, &content, at, &target, round) {
                Ok(Some(choice)) => {
                    Ok(choice.intent_kind == Some(crate::intent::IntentKind::Attack))
                }
                Ok(None) => Ok(false),
                Err(_) => Err(ExprError::UnsupportedKind),
            }
        }

        "event.bool" => {'''),
])

# ============================================================ state.rs：hp_losses
patch('state.rs', [
    ('''    pub health_current: i32,''',
     '''    pub health_current: i32,
    /// §242：这场战斗里**失去生命**的次数（`Blood for Blood` 的费用递减）。
    ///
    /// 与 `cards_played_this_turn` 同一类内核记账：它是一条**规则**的输入（"每次掉血减 1 费"），
    /// 不是某张牌的状态。伤害造成的掉血与 `Lose HP` 都算（StS 的措辞是 "each time you lose HP"，
    /// 不区分来源）。
    ///
    /// ⚠️ model-only：参考没有这个字段 ⇒ 不进 `hash_golden`（参考规范文本里没有它）。
    pub hp_losses: i32,'''),
])

# ============================================================ exec.rs：两处记账
patch('exec.rs', [
    ('''    update_standard_combat_result(ctx.state);
    Ok(lost)''',
     '''    // §242：`Lose HP` 也算"失去生命"（`Blood for Blood` 的费用递减）。
    if lost > 0 {
        if let Some(combatant) = ctx.state.combatant_mut(target) {
            combatant.hp_losses = combatant.hp_losses.saturating_add(1);
        }
    }
    update_standard_combat_result(ctx.state);
    Ok(lost)'''),
])

# 伤害造成的掉血：在 resolve_damage_of_kind 写回 health_current 的地方加一次
s = io.open(K + 'exec.rs', encoding='utf-8').read()
marker = 'let health_lost'
idx = s.index(marker)
# 找该函数体内 health_current 的写入点
window = s[idx:idx + 4000]
target_line = 'combatant.health_current = '
assert window.count(target_line) == 1, window.count(target_line)
abs_idx = idx + window.index(target_line)
line_end = s.index('\n', abs_idx)
s = s[:line_end + 1] + '''        // §242: 每次真的掉血都记一笔（`Blood for Blood` 的费用递减；被格挡吃掉的伤害不算）。
        if health_lost > 0 {
            combatant.hp_losses = combatant.hp_losses.saturating_add(1);
        }
''' + s[line_end + 1:]
io.open(K + 'exec.rs', 'w', encoding='utf-8', newline='\n').write(s)
print('patched exec.rs (hp_losses)')

# ============================================================ play.rs：费用阶段 + 落区规则
patch('play.rs', [
    ('''const SKILL_COST_REDUCTION_STATUS: &str = "standard.skill_cost_reduction";''',
     '''const SKILL_COST_REDUCTION_STATUS: &str = "standard.skill_cost_reduction";

/// §242：`Corruption` 的状态 id（"Skills cost 0. Whenever you play a Skill, Exhaust it."）。
///
/// 与上面几个常量同形：**规则在核心里，状态在内容里**。两条规则都键在它上面 ——
/// 一条费用阶段（`CostStage::CorruptionSkillsFree`），一条落区（`played_card_destination`）。
const CORRUPTION_STATUS: &str = "standard.corruption";

/// §242：`Blood for Blood` 的 tag —— "费用按本场战斗掉血次数递减"。
///
/// 用 tag 而不是新字段，理由与 `x_cost` 完全相同：它是**这张牌的费用语义**，而费用的语义
/// 已经由 tag 表达过一次（`battle::X_COST_TAG`）。
const HP_LOSS_COST_TAG: &str = "hp_loss_cost";'''),
    ('''    DeclarativePassive,
    CardInstance,
}''',
     '''    DeclarativePassive,
    CardInstance,
    /// §242：`Blood for Blood` —— 每失去 1 次生命就便宜 1 点。
    HpLossCount,
    /// §242：`Corruption` —— 技能归 0（`Skills cost 0`）。
    ///
    /// 排在 `DeclarativePassive` **之前**、`CardInstance` **之后**？不：它必须排在
    /// `CardInstance` **之前** —— 每副本价格是"这一份的最终价"，它比任何全局规则都更具体。
    CorruptionSkillsFree,
}'''),
    ('''            CostStage::DeclarativePassive => 1000,
            CostStage::CardInstance => 1100,''',
     '''            CostStage::DeclarativePassive => 1000,
            CostStage::HpLossCount => 210,
            // §242：腐化排在每副本价格（1100）之前 —— "这一份的价格"比"全局规则"更具体。
            CostStage::CorruptionSkillsFree => 1050,
            CostStage::CardInstance => 1100,'''),
    ('''            CostStage::DeclarativePassive => "standard.declarative_card_cost",''',
     '''            CostStage::DeclarativePassive => "standard.declarative_card_cost",
            CostStage::HpLossCount => "standard.hp_loss_cost",
            CostStage::CorruptionSkillsFree => "standard.corruption_cost",'''),
])

s = io.open(K + 'play.rs', encoding='utf-8').read()
# COST_STAGE_ORDER：把新阶段加进去（顺序按 priority）
import re
m = re.search(r'const COST_STAGE_ORDER: \[CostStage; \d+\] = \[(.*?)\];', s, re.S)
assert m, 'COST_STAGE_ORDER not found'
body = m.group(1)
old_const = m.group(0)
new_const = old_const.replace('CostStage::DeclarativePassive,', 'CostStage::DeclarativePassive,\n    CostStage::CorruptionSkillsFree,')
new_const = new_const.replace('[CostStage; 6]', '[CostStage; 8]')
assert new_const != old_const
s = s.replace(old_const, new_const)

# run_cost_stage 的两个新臂
old = '''        // `CombatDecrees.cs:181-203`：本回合第 `Amount` 张免费。法令闸门已否决 ⇒ 恒定原值。
        CostStage::DecreeNthCardFree => Ok(current),'''
new = '''        // `CombatDecrees.cs:181-203`：本回合第 `Amount` 张免费。法令闸门已否决 ⇒ 恒定原值。
        CostStage::DecreeNthCardFree => Ok(current),

        // §242：`Corruption` —— 技能归 0。**绝对值**，不是"减 N"：减 N 需要一个够大的 N，
        // 而那会把"这条规则"写成"减 9"，两者在页面与指纹里长得不一样。
        CostStage::CorruptionSkillsFree => {
            if current <= 0 || !card.is_skill {
                return Ok(current);
            }
            let source = source_of(state, &card.source)?;
            if has_status(source, CORRUPTION_STATUS) {
                return Ok(0);
            }
            Ok(current)
        }

        // §242：`Blood for Blood` —— 每失去 1 次生命就便宜 1 点（下限 0 由 `:474` 的 `max` 兜）。
        // 计的是**本场战斗**（`Combatant::hp_losses`），升级只是把印刷费用改小。
        CostStage::HpLossCount => {
            if current <= 0 {
                return Ok(current);
            }
            // 这张牌自己声明"费用按掉血次数减"吗（tag）？定义 id 从**实例**读
            // （`CardOnTable` 只有 `row`/`instance`，没有定义串）—— 与 `CardInstance` 阶段同一个查法。
            let Some((_, slot)) = find_card_slot(state, &card.source, &card.instance) else {
                return Ok(current);
            };
            let Some(instance) = state.card(slot) else {
                return Ok(current);
            };
            if card
                .content
                .card_has_tag(instance.definition_id.as_str(), HP_LOSS_COST_TAG)
                != Some(true)
            {
                return Ok(current);
            }
            let source = source_of(state, &card.source)?;
            Ok(current.wrapping_sub(source.hp_losses))
        }'''
assert s.count(old) == 1
s = s.replace(old, new)
io.open(K + 'play.rs', 'w', encoding='utf-8', newline='\n').write(s)
print('patched play.rs (cost stages)')
