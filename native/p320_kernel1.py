"""§320 —— 事件窗口的**候选列表**（`EventOffer`）。

两条事件要它（wiki 原文）：

- `The Library` 的 `[Read]`：**从 20 张里选 1 张**加入牌组；
- `Sensory Stone` 的三个 `[Recall]`：**1 张无色牌** / **2 张 + 5 HP** / **3 张 + 10 HP**。

形状与既有的两种"待答"不同：
- `DeckChange` 问的是"**你牌组里的哪一张**"（下标），
- 战斗里的 `PendingChoice::Offered` 是**战斗内**三张候选（容量 3，`ToHand` 语义），
- 这一件是**运行层**：候选由内容池抽、**取一张进牌组**、容量 20。

它复用 `event_next`（与 `DeckChange` 那条完全同一条尾巴），所以"三次 Recall"不需要新状态机 ——
内容把三段的 `Next` 串起来即可。

⚠️ 过滤（无色牌）需要的内容事实是 `PoolCard::colorless`：`rd-run` 不读内容（§133），
所以这条事实由调用方（`rd-wasm`，唯一同时握着内容与池子的那一层）填。
"""

import io
import re

STATE = 'kernel/rd-run/src/state.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d occurrences' % (label, n)
    return t.replace(old, new)


t = io.open(STATE, encoding='utf-8').read()

# ── 1. 容量常量 ────────────────────────────────────────────────────────────────────
t = sub(t, """/// §272：`?` 房的结果（wiki `Unknown Location`）。""",
        """/// §320：事件候选列表的容量 —— wiki 的 `The Library` 是"从 **20 张**里选 1 张"。
///
/// 容量是**语义**：超了要**响亮失败**（`RunError::Capacity`），绝不截断成"少几张候选"。
pub const MAX_EVENT_OFFER: usize = 20;

/// §272：`?` 房的结果（wiki `Unknown Location`）。""",
        'MAX_EVENT_OFFER')

# ── 2. `PoolCard::colorless` ───────────────────────────────────────────────────────
t = sub(t, """    /// §270：its `+` row, if the content has one. Resolved by [`upgraded_id`] in `full_pool`,
    /// **not** by string concatenation at the point of use.
    pub upgraded: Option<&'a str>,
}""",
        """    /// §270：its `+` row, if the content has one. Resolved by [`upgraded_id`] in `full_pool`,
    /// **not** by string concatenation at the point of use.
    pub upgraded: Option<&'a str>,
    /// §320：内容给它打了 `colorless` tag 吗（`Sensory Stone` 的候选**只**从这一半里抽）。
    ///
    /// 为什么是字段而不是"运行层按名字猜"：`rd-run` 不读内容（§133），"哪些牌算无色"写在
    /// `CARD.Tags` 里，只有 `rd-wasm` 看得见。所以这是**调用方填的事实**，与 `kind` 同一条规矩。
    pub colorless: bool,
}""",
        'PoolCard colorless field')

# ── 3. `OfferFilter` ──────────────────────────────────────────────────────────────
t = sub(t, """impl CardKind {
    /// §319：内容/线缆上的拼写""",
        """/// §320：事件候选列表的**池子口径**（`offer_cards:<n>:<filter>` 的第二个载荷）。
///
/// 两个值就是两条内容事实，不多不少：`The Library` 抽角色的整张卡池，`Sensory Stone`
/// 只抽带 `colorless` tag 的那一半。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum OfferFilter {
    /// 整个池子（`any`）。
    Any,
    /// 只要带 `colorless` tag 的行（`colorless`）。
    Colorless,
}

impl OfferFilter {
    /// §320：内容/线缆上的拼写。**唯一一份**（解析、`rd-wasm` 的日志、判据都用它）。
    #[must_use]
    pub fn wire_name(self) -> &'static str {
        match self {
            Self::Any => "any",
            Self::Colorless => "colorless",
        }
    }

    /// 反解析。`None` = 词表外（调用方拒绝，绝不退回 `Any`）。
    #[must_use]
    pub fn from_wire(name: &str) -> Option<Self> {
        Some(match name {
            "any" => Self::Any,
            "colorless" => Self::Colorless,
            _ => return None,
        })
    }

    /// 这一张能进这个池子吗。
    #[must_use]
    fn admits(self, card: &PoolCard<'_>) -> bool {
        match self {
            Self::Any => true,
            Self::Colorless => card.colorless,
        }
    }
}

impl CardKind {
    /// §319：内容/线缆上的拼写""",
        'OfferFilter')

# ── 4. 效果变体 + 解析 ────────────────────────────────────────────────────────────
t = sub(t, """    /// §319：**按类型随机删一张**（`remove_card_random:<kind>`）。`falling` 的
    /// `[Land] Lose (a random Skill)` —— wiki 明写 random，所以它**不是** `DeckChange`：
    /// 没有问句，应用时就地掷一次（`RunStream::Event`）。
    RemoveCardRandom(CardKind),""",
        """    /// §319：**按类型随机删一张**（`remove_card_random:<kind>`）。`falling` 的
    /// `[Land] Lose (a random Skill)` —— wiki 明写 random，所以它**不是** `DeckChange`：
    /// 没有问句，应用时就地掷一次（`RunStream::Event`）。
    RemoveCardRandom(CardKind),
    /// §320：**候选列表**（`offer_cards:<n>:<filter>`）—— 抽 `n` 张互不相同的牌摆在玩家面前，
    /// 他取一张进牌组（`The Library` 的 `[Read]` 20 选 1、`Sensory Stone` 的无色牌）。
    ///
    /// 与 `DeckChange` 的区别是**问的是什么**：`DeckChange` 问"你牌组里的哪一张"，
    /// 这一条问"这几张新的里要哪一张"。两条路都占同一个"待答"位置（`pending`），
    /// 所以内容里一条选项不能**同时**有它们（`resolve_event_effects` 会拒）。
    OfferCards(u8, OfferFilter),""",
        'OfferCards variant')

t = sub(t, """                    "remove_card_random" => match CardKind::from_wire(payload) {""",
        """                    // §320：`offer_cards:<n>:<filter>` —— 数字与口径**都在词里**（`Amount` 无关）。
                    "offer_cards" => {
                        let (count, filter) = payload.split_once(':')?;
                        let count: u8 = count.parse().ok()?;
                        if count == 0 || usize::from(count) > MAX_EVENT_OFFER {
                            return None;
                        }
                        match OfferFilter::from_wire(filter) {
                            Some(filter) => (Self::OfferCards(count, filter), None),
                            None => return None,
                        }
                    }
                    "remove_card_random" => match CardKind::from_wire(payload) {""",
        'parse offer_cards')

# ── 5. `Pending::EventOffer` ──────────────────────────────────────────────────────
t = sub(t, """    /// [`RunState::pick_event_card`] -- an **event** choice that needs a deck index (§143).
    ///
    /// Its own variant rather than a flag on `BlessingCard`: the two are finished by two different
    /// calls, and a shared variant would make "which picker is this?" a condition inside both.
    EventCard = 8,""",
        """    /// [`RunState::pick_event_card`] -- an **event** choice that needs a deck index (§143).
    ///
    /// Its own variant rather than a flag on `BlessingCard`: the two are finished by two different
    /// calls, and a shared variant would make "which picker is this?" a condition inside both.
    EventCard = 8,
    /// §320: [`RunState::pick_event_offer`] -- an event offered a **list of new cards** and waits
    /// for one of them (`The Library`'s 20, `Sensory Stone`'s colorless trio).
    ///
    /// 与 `EventCard` 分开的理由与上一段相同：两条路由两个不同的调用收尾（一个收下标、
    /// 一个收候选槽），合成一个变体会让"这是哪个选择器"变成两处都要判的条件。
    EventOffer = 9,""",
        'Pending::EventOffer')

# ── 6. 状态字段 ───────────────────────────────────────────────────────────────────
t = sub(t, """    pickup_change: Option<DeckChange>,
    pickup_picks: u8,""",
        """    pickup_change: Option<DeckChange>,
    pickup_picks: u8,
    /// §320：事件摊开的候选（`Pending::EventOffer` 时有效；`len` 之外是空 id）。
    ///
    /// 只在"这一段事件已经摊牌、玩家还没选"的窗口里有值；取走一张之后清空。
    event_offer: [RunId; MAX_EVENT_OFFER],
    event_offer_len: u8,""",
        'state fields')

t = sub(t, """            pickup_change: None,""",
        """            pickup_change: None,
            event_offer: [RunId::EMPTY; MAX_EVENT_OFFER],
            event_offer_len: 0,""",
        'state init')

io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs part 1 ok')
