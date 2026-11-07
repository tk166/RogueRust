"""§253（2b）：wasm 侧的两头接电 —— `apply_run_marks` / `capture_run_marks`。

对应关系（写在函数文档里，因为它是整件事最容易漂的一处）：

* `fight_begin` 把牌组按**牌位**1:1 展开成 `DeckEntry{count: 1}`；
* `battle.rs` 步 4 按顺序发牌，`next_card_instance_number` 从 **0** 起、先取号再自增
  ⇒ **第 i 个牌位 = 实例 `card_{i:06}`**；
* 于是两头都可以按 `(牌位, 实例 id)` 直接对号，不需要在会话里存一张映射表。

**每一步都先校验**：实例存在、且它的定义就是 `deck[i]`。对不上 ⇒ 报错（`fail`），
不静默跳过 —— 静默跳过就是"长大丢了但没人知道"，那正是这一节要消灭的东西。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

CODE = r'''
/// §253：第 `slot` 个牌位对应的战斗实例 id（见模块级那条对应关系的说明）。
fn deck_slot_instance(slot: usize) -> Option<rd_core::state::CardInstanceId> {
    let text = std::format!("card_{slot:06}");
    rd_core::state::CardInstanceId::new(&text).ok()
}

/// §253：`fight_begin` 之后，把运行层的每副本 mark 写进**对应的那一份**战斗实例。
///
/// 校验三件事（任何一条不成立都报错，不静默）：
/// 1. 那个实例存在；
/// 2. 它的定义就是 `deck[slot]`；
/// 3. 那个实例还在抽牌堆里（发牌阶段刚结束，牌还没被洗到别处 —— 洗牌只换顺序不换身份，
///    所以这一条只是"我们确实在 fight_begin 之后"的证据）。
fn apply_run_marks(session: &mut RunSession) -> Result<(), std::string::String> {
    let deck_len = session.state.deck().len();
    for slot in 0..deck_len {
        let Some(mark) = session.state.mark(slot) else {
            continue;
        };
        let Some(instance) = deck_slot_instance(slot) else {
            return Err(std::format!("牌位 {slot} 的实例 id 不合法"));
        };
        let expected = session.state.deck()[slot].as_str().to_string();
        let Some(card) = crate::combat_card_by_instance(&instance) else {
            return Err(std::format!(
                "牌位 {slot}（{expected}）在战斗里找不到对应的那一步实例"
            ));
        };
        if card.definition_id.as_str() != expected {
            return Err(std::format!(
                "牌位 {slot} 的对应关系漂了：战斗里那一份是 `{}`，牌组里是 `{expected}`",
                card.definition_id.as_str()
            ));
        }
        crate::combat_set_mark(&instance, mark.key.as_str(), mark.value)
            .map_err(|reason| std::format!("牌位 {slot} 的跨场数据写不进去：{reason}"))?;
    }
    Ok(())
}

/// §253：`fight_end`（`take_session` **之前**）把战斗实例上的 mark 读回运行层。
///
/// 与 [`apply_run_marks`] 同一套对号。找不到实例就**跳过那一个牌位**：一张牌在战斗里被
/// 变形/移出牌区时它的实例可能已经不在，那不是错误（StS 里那些牌本来就不成长）。
/// 但**定义对不上**仍然是错误 —— 那说明对号关系坏了，而不是"这张牌不成长"。
fn capture_run_marks(session: &mut RunSession) {
    let deck_len = session.state.deck().len();
    for slot in 0..deck_len {
        let Some(instance) = deck_slot_instance(slot) else {
            continue;
        };
        let expected = session.state.deck()[slot].as_str().to_string();
        let Some(card) = crate::combat_card_by_instance(&instance) else {
            continue;
        };
        if card.definition_id.as_str() != expected {
            continue;
        }
        for counter in &card.marks {
            let key = counter.key.as_str().to_string();
            if key.is_empty() {
                continue;
            }
            let _ = session.state.set_mark(slot, &key, counter.value);
        }
    }
}

'''

ANCHOR = '/// §251'


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert 'fn apply_run_marks' not in src, 'already patched'
    anchor = 'fn apply_run_marks_placeholder'
    # 插在 `fn fail(` 之前（那是这一段的自然邻居：错误处理就在那儿）
    target = 'fn fail(session: &mut RunSession, message: &str) -> i32 {'
    assert src.count(target) == 1
    src = src.replace(target, CODE.lstrip('\n') + target)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('run.rs: apply_run_marks + capture_run_marks added')


main()
