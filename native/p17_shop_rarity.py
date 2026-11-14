"""§377：商店的有色卡按**稀有度权重**上架（wiki：Rare 9% / Uncommon 37% / Common 54%）。

## 玩家报的现象

"第一次进商店就能低价买到**残杀**和**观察弱点**这种 bug 级别的卡牌。"

**残杀**是 `bludgeon`（Rare，3 费 32 伤），**观察弱点**是 `spot_weakness`（Uncommon）。
在 StS 里第一幕商店能出 Rare，但只有 9% —— 不是"随便就能刷到"。

## 根因

`stock_shop` 的有色卡是这么上的：按**类型**分三组（2 攻 / 2 技 / 1 能力），
每组**在整组里均匀洗牌**取前 N 张。类型构成对（wiki 的 2/2/1），但**稀有度完全没掷** ——
一个组里 Common 有 30 张、Rare 有 5 张，于是 Rare 的实际概率 ≈ 14% 而**且**它还跟
"这一组有几张 Rare" 绑定（内容一变就漂）。玩家看到的是"低价的 Rare 满天飞"。

## 修法

每个货位**先掷档位**（一次 0..99 的 roll，按 wiki 的 9/37/54 分段），再在**该类型 × 该档位**
里均匀取一张；该格子空了就按 wiki 的兜底顺序退：同类型任意档位 → 任意类型任意档位。

wiki 的两条细节一起照做：
* 商店的 roll **受**稀有度保底（`rarity_offset`）影响：档位边界是 `9 + offset`；
* 商店的 roll **不更新**保底（"Shop Cards … do not affect rare offset"）——
  所以这里**不写** `self.rarity_offset`。

保底是负的时候（开局 −5%）稀有档会变成 4%，并且**被裁掉的那部分进 Common**（不是 Uncommon），
与 `reward_bands` 同一个规则 —— 所以这里复用同一个"分段 + 裁剪"的形状。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. 常量 + 分段函数（放在 `reward_bands` 之后）────────────────────────────
ANCHOR = '''/// What a won fight pays (`inv:§5`): gold already granted, plus the cards on offer.'''
assert t.count(ANCHOR) == 1

BLOCK = '''/// 商店有色卡的**稀有度基数**（wiki `Cards` 页「Base chance pre-offset in Shops」）。
///
/// 三个数一起读：Rare 9% / Uncommon 37% / Common 54%（合计 100）。
/// ⚠️ 与战斗奖励的 3/37/60 **不是**同一张表：商店的稀有档更宽（玩家报的"第一次进店就能买到
/// 残杀"就是这个数字没掷的直接后果，见 §377）。
pub const SHOP_RARE_BASE: i32 = 9;
/// 商店 Uncommon 档的**固定宽度**（与 `FightKind::uncommon_width` 同一个含义：它是宽度，
/// 不是概率 —— 档位叠在稀有档上面，稀有档变宽它就往下让）。
pub const SHOP_UNCOMMON_WIDTH: i32 = 37;

/// 商店一张牌的两个档位边界（一次 0–99 的 roll）。
///
/// 规则与 [`reward_bands`] 一致，只换基数：
/// * 稀有档 = `SHOP_RARE_BASE + offset`，**下限 0**；
/// * Uncommon 档 = 稀有档上沿 + `SHOP_UNCOMMON_WIDTH`，**被裁掉的下界部分进 Common**。
///
/// wiki 明说商店的 roll *受*保底影响但**不更新**它（"Shop Cards … do not affect rare offset,
/// however they are affected by rare chance"），所以调用方掷完**不许**动 `rarity_offset`。
#[must_use]
pub const fn shop_bands(offset: i32) -> (i32, i32) {
    let banded = SHOP_RARE_BASE + offset;
    let rare_top = if banded < 0 { 0 } else { banded };
    let clipped = if banded < 0 { -banded } else { 0 };
    (rare_top, rare_top + SHOP_UNCOMMON_WIDTH - clipped)
}

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

# ── 2. 重写有色卡上架：先掷档位，再在（类型 × 档位）里取 ────────────────────
OLD_START = '''        // ── 有色卡：2 攻 / 2 技 / 1 能力 ────────────────────────────────────────
        // 先把"这一类有几张"数出来，再在**类内**洗牌取前 N 张 —— 分类是构成，洗牌是随机。
        let wanted = [(CardKind::Attack, 2usize), (CardKind::Skill, 2), (CardKind::Power, 1)];'''
assert t.count(OLD_START) == 1

OLD_END = '''        // 分类不足时**补位**：内容里某一类（通常是 Power）不够 2 张、或池子里的牌没有类型标签时，
        // 从其余的**非无色**牌里补齐。空着整排不是"更忠实"，而是"商店没东西卖"。'''
assert t.count(OLD_END) == 1

start = t.index(OLD_START)
end = t.index(OLD_END)

NEW = '''        // ── 有色卡：2 攻 / 2 技 / 1 能力，**每个货位先掷稀有度档位** ─────────────
        //
        // wiki（`Cards` 页）：商店的档位是 Rare 9% / Uncommon 37% / Common 54%，
        // 且**受**稀有度保底影响、**不更新**保底。
        //
        // ⚠️ 旧实现只做了"2 攻 / 2 技 / 1 能力"的**类型**构成，稀有度**完全没掷** ——
        // 一个类型组里 Common 三十张、Rare 五张，于是 Rare 的概率变成"组里 Rare 的占比"
        // （≈14%，而且内容一变就漂）。玩家实测"第一次进商店就能低价买到残杀（Rare）"。
        let wanted = [(CardKind::Attack, 2usize), (CardKind::Skill, 2), (CardKind::Power, 1)];
        let mut shelved_cards = 0usize;
        for (kind, count) in wanted {
            for _ in 0..count {
                if shelved_cards == MAX_SHOP_CARDS {
                    break;
                }
                // ① 掷档位（一次 roll，两个边界）。
                let (rare_top, uncommon_top) = shop_bands(self.rarity_offset);
                let roll = self.rng.roll(RunStream::Shop, 100)? as i32;
                let band = if roll < rare_top {
                    Rarity::Rare
                } else if roll < uncommon_top {
                    Rarity::Uncommon
                } else {
                    Rarity::Common
                };
                // ② 在（这一类型 × 这一档位）里均匀取一张，跳过已经上架的。
                let mut members = [0u8; MAX_POOL];
                let mut found = 0usize;
                for (index, card) in card_pool.iter().enumerate() {
                    if card.colorless || card.kind != kind || card.rarity != band {
                        continue;
                    }
                    if self.shop.cards[..shelved_cards]
                        .iter()
                        .any(|offer| offer.id.as_str() == card.id)
                    {
                        continue;
                    }
                    if found == MAX_POOL {
                        return Err(RunError::EmptyPool("cards"));
                    }
                    members[found] = index as u8;
                    found += 1;
                }
                // ③ 兜底：档位里没货 ⇒ 同类型任意档位（wiki 没有明说这一条，但"空着一个货位"
                //    比"换个档位"更糟；这条与 `stock_shop` 原来的补位是同一个理由）。
                if found == 0 {
                    for (index, card) in card_pool.iter().enumerate() {
                        if card.colorless || card.kind != kind {
                            continue;
                        }
                        if self.shop.cards[..shelved_cards]
                            .iter()
                            .any(|offer| offer.id.as_str() == card.id)
                        {
                            continue;
                        }
                        if found == MAX_POOL {
                            return Err(RunError::EmptyPool("cards"));
                        }
                        members[found] = index as u8;
                        found += 1;
                    }
                }
                if found == 0 {
                    continue; // 这一类型整个池子都空了 ⇒ 交给下面的补位
                }
                let pick = self.rng.roll(RunStream::Shop, found as u32)? as usize;
                let card = card_pool[members[pick] as usize];
                let (low, high) = card_price_band(card.rarity);
                let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
                self.shop.cards[shelved_cards] = Offer {
                    id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                    price: self.marked_up(price),
                };
                shelved_cards += 1;
            }
            if shelved_cards == MAX_SHOP_CARDS {
                break;
            }
        }
        // ⚠️ 这里**不写** `self.rarity_offset`：wiki 明说商店的 roll 不更新保底。
'''

t = t[:start] + NEW + t[end:]

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('stock_shop: 稀有度档位 9/37/54')
