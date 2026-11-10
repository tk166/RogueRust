"""§322a —— `card:<id>` / `curse:<id>` 的 `Amount` 现在真的生效。

发现：内容里 `winding_halls` 写 `card:madness` Amount **2**、§321 的 `[I am Rich]` 写
`curse:normality` Amount **2**，而内核**只给一张** —— `parse` 把 `amount` 丢掉了，`apply`
也只 `push_card` 一次。这是一个安静的错：屏幕上是"2 张"，牌组里是 1 张。

修法：两个变体带上张数（`GainCurse(u8)` / `GainCard(u8)`），`Amount` 走 `1..=5`
（真内容最多的是 `vampires` / `council_of_ghosts` 的 5 张；> 5 或 < 0 ⇒ 解析失败，不截断）。
"""

import io
import re

STATE = 'kernel/rd-run/src/state.rs'
WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(STATE, encoding='utf-8').read()

t = sub(t, """    /// §290：给**指定**的一张牌（`card:<id>`）。与 `GainCurse` 的区别只有一条：""",
        """    /// §290：给**指定**的一张牌（`card:<id>`），`n` = 张数（`Amount`，1..=5）。
    /// §322：`Amount` 以前被**静默丢掉**（写 2 张只给 1 张），现在它是这个字段。
    /// 与 `GainCurse` 的区别只有一条：""", 'GainCard doc')

t = sub(t, """    GainCard,""", """    GainCard(u8),""", 'GainCard variant')
t = sub(t, """    GainCurse,""", """    /// §322：诅咒的张数（`Amount`，1..=5）。`mind_bloom` 的 `[I am Rich]` 是 **2 张** Normality。
    GainCurse(u8),""", 'GainCurse variant')

t = sub(t, """                    "curse" => (Self::GainCurse, Some(payload)),""",
        """                    // §322：张数在 `Amount` 里（1..=5）。0 / 负数 / > 5 ⇒ **解析失败**
                    // （不截断、也不当 1 —— 一条写错的 `Amount` 应该响亮）。
                    "curse" => match card_count(amount) {
                        Some(count) => (Self::GainCurse(count), Some(payload)),
                        None => return None,
                    },""", 'parse curse')

t = sub(t, """                    "card" => (Self::GainCard, Some(payload)),""",
        """                    "card" => match card_count(amount) {
                        Some(count) => (Self::GainCard(count), Some(payload)),
                        None => return None,
                    },""", 'parse card')

# `card_count` 放在 `parse_permille` 旁边（同一个"词里的数"家族）。
t = sub(t, """/// §280：把 `"25"` / `"12.5"` 这样的**百分字符串**解成千分值（`250` / `125`）。""",
        """/// §322：`card:<id>` / `curse:<id>` 的**张数**（`Amount`）。
///
/// `0`（以及缺省的 0）读作 1 —— 内容里绝大多数这两个原子都不用 `Amount`；但**别的**数字必须落在
/// `1..=5`：真内容里最多的是 `vampires` / `council_of_ghosts` 的 5 张，写 6 张是内容错误。
fn card_count(amount: i32) -> Option<u8> {
    match amount {
        0 => Some(1),
        1..=5 => u8::try_from(amount).ok(),
        _ => None,
    }
}

/// §280：把 `"25"` / `"12.5"` 这样的**百分字符串**解成千分值（`250` / `125`）。""",
        'card_count helper')

# 应用：张数循环。
t = sub(t, """            EventEffect::GainCurse => {""", """            EventEffect::GainCurse(count) => {""", 'apply curse head')
t = sub(t, """                // `curse:` 载荷按定义就是诅咒（上面刚验过池子里它是 `Rarity::Curse`）。
                self.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain(id) })?;""",
        """                // `curse:` 载荷按定义就是诅咒（上面刚验过池子里它是 `Rarity::Curse`）。
                // §322：张数（`omamori` 每张各挡一次 —— 那是 `push_card` 的规则，别在这里另记一套）。
                for _ in 0..count {
                    self.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain(id) })?;
                }""", 'apply curse loop')

t = sub(t, """            EventEffect::GainCard => {""", """            EventEffect::GainCard(count) => {""", 'apply card head')
t = sub(t, """                self.push_card(*row)?;
            }
            EventEffect::LoseAllGold => {""",
        """                // §322：张数。牌组满了 ⇒ `push_card` 的 `Capacity`（响亮，不静默丢牌）。
                for _ in 0..count {
                    self.push_card(*row)?;
                }
            }
            // §279：**失去**旁边那件遗物""", 'apply card loop')

io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: card/curse counts ok')

# wasm 的两个表
t = io.open(WASM, encoding='utf-8').read()
t = sub(t, """        | EventEffect::GainCard""", """        | EventEffect::GainCard(_)""", 'wasm GainCard code')
t = sub(t, """        | EventEffect::GainCurse""", """        | EventEffect::GainCurse(_)""", 'wasm GainCurse code')
io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm effect tables ok')
