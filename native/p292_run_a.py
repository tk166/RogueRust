"""§292 Wave 1：rd-run 的载体（`Nothing` / 拾取欠账 / 宝箱三件 / 稀有档倍率 / 药水倍率）。

## 为什么这些遗物"便宜"

它们的钩子都**已经在运行层**（拾取、宝箱、奖励、药水），缺的只是：

| 载体 | 遗物 |
|---|---|
| 一个新变体 `Nothing`（wiki 上就是一句 flavor） | `cultist_headpiece` `spirit_poop` |
| 战斗结束再涨上限（`end_of_combat` 已有 `EndOfCombatHeal`） | `face_of_cleric` |
| **宝箱**这一格（`open_chest` 里三个判断） | `matryoshka` `nloths_hungry_face` `cursed_key` |
| **拾取欠账**（`push_relic` 拿不到遗物池/药水池 ⇒ 记欠账，调用方兑现） | `calling_bell` `cauldron` |
| 牌组编辑多一种（`DeckChange::Duplicate`） | `dollys_mirror` |
| 奖励稀有档宽度 | `nloths_gift` |
| 药水效果倍率 | `sacred_bark` |

⚠️ 拾取欠账**不是**"抄一份内容"：`push_relic` 的签名只有卡池（它给 `war_paint` 看牌的类型），
而 `calling_bell` 要 3 件**遗物**、`cauldron` 要 5 瓶**药水** —— 两个池都在调用方手里。
把签名加两个参数会动到 800 条判据里的每一次 `push_relic` 调用；记欠账则"谁有池子谁兑现"，
并且欠账**进 run hash**（它是玩家可见的欠着的东西）。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:110])
    return text.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── A. 新变体（挂在 `RestCardReward` 之后，枚举的最后一个）
    s = patch(s, '''    /// §259: resting also pays a card reward (`dream_catcher`).
    RestCardReward,
}''', '''    /// §259: resting also pays a card reward (`dream_catcher`).
    RestCardReward,
    /// §292：wiki 上只有一句 flavor（`cultist_headpiece`：*"You feel more talkative."*、
    /// `spirit_poop`：*"It's unpleasant."*）。**"没有效果"也是一种效果**：它在表里有名字，
    /// 于是"内核认识这件遗物"与"它什么都不做"可以同时成立 —— 而不是靠"表里查不到"来表示，
    /// 那会让 `UnsupportedRelic` 把一件合法的遗物挡在腰带外面。
    Nothing,
    /// §292：`face_of_cleric` —— 战斗结束时**永久** +1 最大生命（wiki: *"At the end of combat,
    /// raise your Max HP by 1."*）。与 `MaxHealthUp` 的区别只是**时点**：那个在拾取那一刻。
    EndOfCombatMaxHealthUp(i32),
    /// §292：`matryoshka` —— 接下来 `chests` 个**非 Boss** 宝箱各给**两件**遗物。
    ChestExtraRelic { chests: u8 },
    /// §292：`nloths_hungry_face` —— 接下来 `chests` 个非 Boss 宝箱是**空的**。
    NextChestEmpty(u8),
    /// §292：`cursed_key` —— 每开一个非 Boss 宝箱，牌组里多一张随机诅咒。
    ///
    /// 它是**第二半**（第一半是每回合 +1 能量，走 `StartCombatStatus`），所以挂在
    /// [`RELIC_SECOND_HALVES`] 里。
    ChestAddsCurse,
    /// §292：`calling_bell` —— 拾取时给一张**指名**诅咒 + `relics` 件遗物。
    ///
    /// 遗物给不出来（`push_relic` 没有遗物池）⇒ 记成**欠账**，由调用方兑现
    /// （[`RunState::pickup_relics`]）。
    PickupCurseAndRelics {
        /// 内容的 `CARD` 行 id（`curse_of_the_bell`）。
        curse: &'static str,
        /// 还给几件遗物。
        relics: u8,
    },
    /// §292：`cauldron` —— 拾取时酿 `count` 瓶随机药水。
    ///
    /// 同一条欠账通道：[`RunState::pickup_potions`]。腰带满了就停（见 §292 的偏差记录）。
    PickupPotions(u8),
    /// §292：`dollys_mirror` —— 拾取时**复制**一张牌（玩家选，`DeckChange::Duplicate`）。
    PickupDuplicate(u8),
    /// §292：`nloths_gift` —— 战斗奖励里**稀有档**的宽度乘以 `times`（wiki: *"Triples the
    /// chance of finding Rare cards"*）。
    RareCardChanceMultiplier(i32),
    /// §292：`sacred_bark` —— 药水效果乘以 `percent`（wiki: *"Double the effectiveness"* = 200）。
    PotionEffectPercent(i32),
}''')

    # ── B. 第二半表：`cursed_key`
    s = patch(s, '''const RELIC_SECOND_HALVES: [(&str, RelicEffect); 4] = [''',
                  '''const RELIC_SECOND_HALVES: [(&str, RelicEffect); 5] = [''')
    s = patch(s, '''    // §273：`the_courier` 的第一半是 -20%（`ShopDiscountPercent`），第二半是"买完补货"。
    ("the_courier", RelicEffect::CourierRestock),''',
                  '''    // §273：`the_courier` 的第一半是 -20%（`ShopDiscountPercent`），第二半是"买完补货"。
    ("the_courier", RelicEffect::CourierRestock),
    // §292：`cursed_key` 的第一半是每回合 +1 能量，第二半是"非 Boss 宝箱里多一张诅咒"。
    ("cursed_key", RelicEffect::ChestAddsCurse),''')

    # ── C. 新字段（挂在 `ascension` 之前，结构体的末尾）
    s = patch(s, '''    /// The Ascension level, `0`..=[`MAX_ASCENSION`] (§159). Cumulative: level `N` carries rules
    /// `1..=N`, and every rule asks [`RunState::at_least`] for its own number.
    ascension: u8,
}''', '''    /// The Ascension level, `0`..=[`MAX_ASCENSION`] (§159). Cumulative: level `N` carries rules
    /// `1..=N`, and every rule asks [`RunState::at_least`] for its own number.
    ascension: u8,
    /// §292：`matryoshka` —— 还剩几个非 Boss 宝箱会给**两件**遗物（0 = 没有）。
    ///
    /// 计数而不是布尔：wiki 是 "The **next 2** non-boss chests"。
    chest_extra: u8,
    /// §292：`nloths_hungry_face` —— 还剩几个非 Boss 宝箱是空的（wiki: "The **next** non-Boss
    /// chest"，所以只有 1）。
    chest_empty: u8,
    /// §292：拾取时**欠着**的遗物件数（`calling_bell` 的 3 件）。
    ///
    /// 为什么是欠账：`push_relic` 只拿得到**卡池**（拾取类遗物要看牌的类型），遗物池在调用方
    /// 手里。把签名加一个参数会动到每一次 `push_relic` 调用（包括 800 条判据），而记欠账的
    /// 语义更清楚 —— "这件遗物的另外三件**还没到**，谁有池子谁付"。
    pickup_relics: u8,
    /// §292：拾取时**欠着**的几瓶药水（`cauldron` 的 5 瓶）。同 [`Self::pickup_relics`]。
    pickup_potions: u8,
}''')

    # ── D. 初始化
    s = patch(s, '''            rarity_offset: RARITY_OFFSET_START,
            ascension,''', '''            rarity_offset: RARITY_OFFSET_START,
            ascension,
            chest_extra: 0,
            chest_empty: 0,
            pickup_relics: 0,
            pickup_potions: 0,''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('A-D done')


main()
