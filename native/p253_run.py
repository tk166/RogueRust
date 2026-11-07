"""§253（2/2）：`ritual_dagger` 的**跨场成长**。

## 缺口在哪

`Ritual Dagger` 的 "If Fatal, permanently increase this card's damage by 3" 里那个
**permanently 是跨战斗的**（跟着牌组里那一份副本走）。而运行层把牌组压成
`(定义 id, 张数)` 交给战斗（`rd-wasm/src/run.rs` 里那段 `counts`），**每副本身份在那一步就丢了** ——
所以 §250 只能做到"这场战斗内长大"，并把这条写成偏差。

## 怎么补（三处，缺一不可）

1. **运行层留一格**：`RunState.marks: [RunMark; MAX_RUN_DECK]` —— 每个**牌位**一个
   `(key, value)`。`key` 是 mark counter 的名字（`standard.ritual_dagger_bonus`），
   `value` 是它的值。不写进 run hash（与 `gold_carried_away` 同一条：这不是参考的字段）。
   **牌组重排时它必须跟着走**（`remove_card` 会 `deck[i] = deck[i+1]`）—— 那是这一节最容易漏的一处，
   漏了就会"删掉一张牌，另一张牌继承了它的伤害"。
2. **牌位 ↔ 战斗实例的对应**：现在是 `(id, count)` 分组，分组会**打乱顺序**
   （`[dagger, strike, dagger]` 变成 `[(dagger,2),(strike,1)]`），于是"第 i 个实例"对不上"第 i 个牌位"。
   改成**一个牌位一条 `DeckEntry`（count 1）**，顺序就与 `deck()` 逐字一致；而发牌是**按顺序**取号
   （`battle.rs` 步 4：`next_card_instance_number` 从 **0** 起，先取号再自增），所以
   第 i 个牌位 = 实例 `card_{i:06}`。这条假设**自带校验**：应用之前先确认那份实例的定义
   就是 `deck[i]`，对不上就报错（不静默跳过 —— 静默跳过就是"长大消失"的那种难查 bug）。
3. **两头接**：`fight_begin` 装好战斗之后把运行层的 mark 写进对应的实例；`fight_end`
   （`take_session` **之前**）把实例上的 mark 读回运行层。

## 为什么只有一格

一张牌同时需要两个跨场计数器时再加（StS 里今天没有这种牌）。**一格**是刻意的：
`MAX_RUN_DECK × (41B id + 4B)` ≈ 2.7 KB，而 `RunState` 有 8 KB 的 tripwire ——
先按真实需要给，不够再抬（抬 tripwire 正是那条 todo 说的做法）。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

RUN_PATCHES = [
    # 1) 类型
    ('''/// A deck/relic/potion id. `Ident<ID_CAP>` is 41 bytes (`ID_CAP` 40 + a length byte).
pub type RunId = Ident<ID_CAP>;''',
     '''/// A deck/relic/potion id. `Ident<ID_CAP>` is 41 bytes (`ID_CAP` 40 + a length byte).
pub type RunId = Ident<ID_CAP>;

/// §253：**跟着牌位走的一格每副本数据**（`key` = mark counter 的名字，`value` = 它的值）。
///
/// 存在的理由只有一条：`Ritual Dagger` 的 "permanently increase this card's damage by 3"
/// 里那个 *permanently* 是**跨战斗**的，而战斗层的一次性实例在 `fight_end` 就没了。
///
/// ⚠️ 它**不进 run hash**（`hash.rs` 逐字段写）：参考的运行层没有这个概念，而那个指纹要与
/// 参考对齐。与 §201 的 `CombatState.gold_carried_away` 同一条裁决。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RunMark {
    /// mark counter 的名字；`RunId::EMPTY` = 这个牌位没有跨场数据。
    pub key: RunId,
    /// 它的值。
    pub value: i32,
}

impl RunMark {
    /// 没有跨场数据。
    pub const NONE: Self = Self {
        key: RunId::EMPTY,
        value: 0,
    };

    /// 这一格是不是空的。
    #[must_use]
    pub fn is_none(self) -> bool {
        self.key.as_str().is_empty()
    }
}'''),
    # 2) 字段
    ('''    deck: [RunId; MAX_RUN_DECK],
    deck_len: u8,''',
     '''    deck: [RunId; MAX_RUN_DECK],
    /// §253：与 `deck` **同下标**的每副本数据（`RunMark::NONE` = 没有）。
    /// 牌组重排时必须跟着搬（`remove_card` 里那条 `deck[i] = deck[i+1]` 旁边的同一行）。
    marks: [RunMark; MAX_RUN_DECK],
    deck_len: u8,'''),
    # 3) 初始化
    ('''            deck: [RunId::EMPTY; MAX_RUN_DECK],''',
     '''            deck: [RunId::EMPTY; MAX_RUN_DECK],
            marks: [RunMark::NONE; MAX_RUN_DECK],'''),
]

# 4) 访问器 + 5) `remove_card` 跟着搬
ACCESSORS = (
    '''    /// The relics, in acquisition order.''',
    '''    /// §253：第 `slot` 个牌位的跨场 mark（`None` = 那个牌位没有）。
    ///
    /// `slot` 越界 ⇒ `None`（查询不是写入，越界没有可报告的东西）。
    #[must_use]
    pub fn mark(&self, slot: usize) -> Option<RunMark> {
        if slot >= self.deck_len as usize {
            return None;
        }
        self.marks.get(slot).copied().filter(|mark| !mark.is_none())
    }

    /// §253：写一个牌位的跨场 mark（`key` 为空 ⇒ 清掉）。越界 ⇒ 拒绝。
    ///
    /// **拒绝而不是扩写**：牌位是牌组的，写一个不存在的牌位说明调用方算错了下标，
    /// 而"多出来的那一格"永远没有人读 —— 那是静默丢数据。
    pub fn set_mark(&mut self, slot: usize, key: &str, value: i32) -> Result<(), RunError> {
        if slot >= self.deck_len as usize {
            return Err(RunError::SlotOutOfRange);
        }
        if key.is_empty() {
            if let Some(cell) = self.marks.get_mut(slot) {
                *cell = RunMark::NONE;
            }
            return Ok(());
        }
        let id = RunId::new(key)?;
        if let Some(cell) = self.marks.get_mut(slot) {
            *cell = RunMark { key: id, value };
        }
        Ok(())
    }

    /// The relics, in acquisition order.''')


def patch(path, pairs, label):
    src = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert src.count(old) == 1, (label, old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched', label)


def main():
    patch(RUN, RUN_PATCHES + [ACCESSORS], 'rd-run/state.rs (type + field + init + accessors)')

    # `remove_card`：牌位搬家时 mark 必须一起搬。
    src = io.open(RUN, encoding='utf-8').read()
    old = '''            self.deck[index] = self.deck[index + 1];'''
    assert src.count(old) == 1, src.count(old)
    src = src.replace(old, '''            self.deck[index] = self.deck[index + 1];
            // §253：**mark 跟着牌走**。漏了这一行就会出现"删掉一张牌，另一张继承了它的伤害" ——
            // 而那在页面上完全看不出来（两张牌都还在，只是数字变了）。
            self.marks[index] = self.marks[index + 1];''')
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched rd-run/state.rs (remove_card shifts marks)')


main()
