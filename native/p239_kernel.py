"""§239 内核：`clash` 的 PlayCondition 事实位 + 事实位加宽到 u16。

`PlayCondition` 的校验器（`play.rs:1429`）早就实现了，缺的是**它求值时可以问的一个事实**：
"这次出牌时手牌全是攻击牌吗"。这个事实要在**有内容的地方**算（卡的 tag 在 CARD 表里，不在状态里），
所以照 `event_flags` 的既有办法：由派发方算好、写进位图，内容用 `event.bool` 问。

事实位从 u8 抬到 u16：bit 0..7 已经全部有主（4 个卡牌 tag + status + curse + isResolving +
hpLossFromCard + damageIsAttack —— 实际 9 个定义挤在 8 位里，**curse 与 damage.isAttack 抢过**），
再加一位就必须加宽。加宽是机械改动（编译器会把每一处点出来）。
"""
import io
import re

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


# ---------------------------------------------------------------- exec.rs：加宽 + 新位 + 常量
patch('exec.rs', [
    ('    pub event_flags: u8,', '    pub event_flags: u16,'),
    ('pub const DAMAGE_IS_ATTACK: u8 = 1 << 4;', 'pub const DAMAGE_IS_ATTACK: u16 = 1 << 4;'),
    ('pub const CARD_HAS_TAG_ATTACK: u8 = 1 << 0;', 'pub const CARD_HAS_TAG_ATTACK: u16 = 1 << 0;'),
    ('pub const CARD_HAS_TAG_SKILL: u8 = 1 << 1;', 'pub const CARD_HAS_TAG_SKILL: u16 = 1 << 1;'),
    ('pub const CARD_HAS_TAG_POWER: u8 = 1 << 2;', 'pub const CARD_HAS_TAG_POWER: u16 = 1 << 2;'),
    ('pub const CARD_HAS_TAG_STATUS: u8 = 1 << 3;', 'pub const CARD_HAS_TAG_STATUS: u16 = 1 << 3;'),
    ('pub const CARD_HAS_TAG_CURSE: u8 = 1 << 7;', 'pub const CARD_HAS_TAG_CURSE: u16 = 1 << 7;'),
    ('pub const CARD_IS_RESOLVING: u8 = 1 << 5;', 'pub const CARD_IS_RESOLVING: u16 = 1 << 5;'),
    ('pub const HP_LOSS_FROM_CARD: u8 = 1 << 6;', 'pub const HP_LOSS_FROM_CARD: u16 = 1 << 6;'),
    ('''pub const CARD_HAS_TAG_CURSE: u16 = 1 << 7;''',
     '''pub const CARD_HAS_TAG_CURSE: u16 = 1 << 7;

/// §239：**这次出牌时，手牌里每一张都是 Attack**（`Clash` 的 `PlayCondition` 问的就是它）。
///
/// 为什么是"一位、一个问题"，不是"每位一个 tag"：这个事实只有 `PlayCondition` 会问，而
/// `PlayCondition` 在**出牌校验**时求值 —— 那一刻有内容（能查卡牌 tag），所以由校验器算好这一位。
/// 位宽的其它 8 位都是"事件事实"，这一位是"出牌前提"，靠注释与命名分开（`playCondition.` 前缀）。
///
/// ⚠️ 它**只在出牌校验时**被填。别的地方问它会得到 0（= false），所以
/// `sts_content_check.py` 有一条判据：`playCondition.*` 这个键只许出现在卡的 `PlayCondition` 里。
pub const PLAY_CONDITION_HAND_ALL_ATTACKS: u16 = 1 << 8;'''),
])

# ---------------------------------------------------------------- content.rs / host.rs：返回类型
patch('content.rs', [('    pub fn card_tag_bits(&self, card: &str) -> u8 {\n        let mut bits = 0u8;',
                      '    pub fn card_tag_bits(&self, card: &str) -> u16 {\n        let mut bits = 0u16;')])

s = io.open(K + 'host.rs', encoding='utf-8').read()
# card_tag_flags 返回 u8 -> u16
s2 = s.replace('fn card_tag_flags(content: &Content<\'_>, definition_id: &str) -> u8 {',
               'fn card_tag_flags(content: &Content<\'_>, definition_id: &str) -> u16 {')
assert s2 != s
s = s2
# run_triggers_with_flags 的 flags: u8 -> u16
s2 = s.replace('        event: TriggerEvent,\n        flags: u8,\n    ) -> Result<(), HostError> {',
               '        event: TriggerEvent,\n        flags: u16,\n    ) -> Result<(), HostError> {')
assert s2 != s
io.open(K + 'host.rs', 'w', encoding='utf-8', newline='\n').write(s2)
print('patched host.rs (u16)')

# ---------------------------------------------------------------- play.rs：校验器算那一位
patch('play.rs', [
    ('''    let condition = NodeRef::new(card.content, term_id);
    let context = ExprContext {
        state,
        source: Some(card.source),
        event_target: card.target,
        iteration_target: None,
        iteration_card: None,
        resolving_card: None,
        // §195.1: a `PlayCondition` is evaluated outside any event, so there is no amount to read
        // (`eventAmount` reports `NoTarget` rather than 0).
        event_flags: 0,
        event_amount: None,
        x_cost: 0,
    };''',
     '''    let condition = NodeRef::new(card.content, term_id);
    let context = ExprContext {
        state,
        source: Some(card.source),
        event_target: card.target,
        iteration_target: None,
        iteration_card: None,
        resolving_card: None,
        // §195.1: a `PlayCondition` is evaluated outside any event, so there is no amount to read
        // (`eventAmount` reports `NoTarget` rather than 0).
        //
        // §239: the one fact a `PlayCondition` *can* ask about is the hand (`Clash`). It is computed
        // **here** because this is the only place that has both the state and the content -- the
        // cards' tags live in the `CARD` table, which `CombatState` does not own.
        event_flags: crate::exec::PLAY_CONDITION_HAND_ALL_ATTACKS * u16::from(hand_is_all_attacks(state, card)),
        event_amount: None,
        x_cost: 0,
    };'''),
    ('''/// #4 one_attack_per_turn（Priority 200，`standard.one_attack_per_turn_validator`）。''',
     '''/// §239：手牌里**每一张**都是 Attack 吗（`Clash` 的前提）。
///
/// 空手牌算真（`all()` 的真空真值）—— 与 StS 无关但**不许**把它当假：那条路走不到
/// （空手牌时没有牌可打），而"空手牌 ⇒ 条件为假"会让 `Clash` 在某种边角上无故被拒。
///
/// ⚠️ 正在结算的那张牌**仍在手牌里**（§225：落区在终态回调），而它的 `PlayCondition` 是在出牌
/// **之前**求值的 —— 所以这里看到的是"手上所有的牌，包括 `Clash` 自己"。`Clash` 自己是 Attack，
/// 于是答案相同；写在这里是因为**换个牌名就可能不同**（将来若有"手牌全是技能"的牌，自己就会被算进去）。
fn hand_is_all_attacks(state: &CombatState, card: &CardOnTable<'_>) -> bool {
    let Some(zones) = state.card_zones(&card.source) else {
        return true;
    };
    let mut slot = 0usize;
    while let Some(index) = zones.slot_at(CardZone::Hand, slot) {
        slot += 1;
        let Some(instance) = state.card(index) else {
            continue;
        };
        if card
            .content
            .card_has_tag(instance.definition_id.as_str(), "attack")
            != Some(true)
        {
            return false;
        }
    }
    true
}

/// #4 one_attack_per_turn（Priority 200，`standard.one_attack_per_turn_validator`）。'''),
])

# ---------------------------------------------------------------- expr.rs：新键
patch('expr.rs', [
    ('''                "hpLoss.fromCard" => crate::exec::HP_LOSS_FROM_CARD,''',
     '''                "hpLoss.fromCard" => crate::exec::HP_LOSS_FROM_CARD,
                // §239: the one fact a `PlayCondition` can ask about (`Clash`). Read only while a
                // card's `PlayCondition` is being evaluated -- `sts_content_check.py` enforces that.
                "playCondition.handIsAllAttacks" => crate::exec::PLAY_CONDITION_HAND_ALL_ATTACKS,'''),
])
print('done')
