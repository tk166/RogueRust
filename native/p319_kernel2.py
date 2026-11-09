"""§319 第二半 —— `CardKind` 词表、`RemoveCardRandom`、错误变体、`rd-wasm` 的 `deck_tags`。

（第一半 `p319_kernel.py` 已经把 `RunFacts::deck_tags` 与条件原子 `card_tag` 落盘了；
这个文件之所以存在：那条锚点少写了一行 `#[derive(...)]`，重跑第一半会插第二遍字段。）
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
STREAMS = 'kernel/rd-run/src/streams.rs'
WASM = 'kernel/rd-wasm/src/run.rs'


def read(path):
    return io.open(path, encoding='utf-8').read()


def write(path, text):
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text)


def sub_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, '%s: expected 1 occurrence, found %d' % (label, n)
    return text.replace(old, new)


t = read(STATE)
t = sub_once(
    t,
    """/// A card as the reward roll sees it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolCard<'a> {""",
    """impl CardKind {
    /// §319：内容/线缆上的拼写（`attack` / `skill` / `power` / `curse` / `status` / `other`）。
    ///
    /// **唯一一份**：`remove_card_random:<kind>` 的解析、`rd-wasm` 填 `RunFacts::deck_tags`、
    /// 以及条件原子 `card_tag` 的 `Id` 都用它。抄第二份的代价是"事件能删、条件认不出"，
    /// 而这种漂不会让任何判据变红（§161 的 `known` 表就是这么漏的）。
    #[must_use]
    pub fn wire_name(self) -> &'static str {
        match self {
            Self::Attack => "attack",
            Self::Skill => "skill",
            Self::Power => "power",
            Self::Status => "status",
            Self::Curse => "curse",
            Self::Other => "other",
        }
    }

    /// 反解析。`None` = 词表外（调用方**拒绝**，绝不退回 `Other`）。
    ///
    /// 退回 `Other` 会让 `remove_card_random:powerr` 变成"删一张类型未知的牌"，
    /// 也就是一条拼错的内容**安静地**删错牌。
    #[must_use]
    pub fn from_wire(name: &str) -> Option<Self> {
        Some(match name {
            "attack" => Self::Attack,
            "skill" => Self::Skill,
            "power" => Self::Power,
            "status" => Self::Status,
            "curse" => Self::Curse,
            "other" => Self::Other,
            _ => return None,
        })
    }
}

/// A card as the reward roll sees it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolCard<'a> {""",
    'CardKind impl')

t = sub_once(
    t,
    """    /// Replace a named deck card with a random one.
    TransformCard,
""",
    """    /// Replace a named deck card with a random one.
    TransformCard,
    /// §319：**按类型随机删一张**（`remove_card_random:<kind>`）。`falling` 的
    /// `[Land] Lose (a random Skill)` —— wiki 明写 random，所以它**不是** `DeckChange`：
    /// 没有问句，应用时就地掷一次（`RunStream::Event`）。
    RemoveCardRandom(CardKind),
""",
    'RemoveCardRandom variant')

t = sub_once(
    t,
    """                match kind {
                    "curse" => (Self::GainCurse, Some(payload)),
""",
    """                match kind {
                    // §319：`falling` —— `remove_card_random:<kind>`（载荷是**类型**，不是卡 id）。
                    "remove_card_random" => match CardKind::from_wire(payload) {
                        Some(kind) => (Self::RemoveCardRandom(kind), None),
                        // 拼错的类型**不是** `Other`：那会"删一张不知道什么类型的牌"。
                        None => return None,
                    },
                    "curse" => (Self::GainCurse, Some(payload)),
""",
    'parse remove_card_random')

t = sub_once(
    t,
    """            EventEffect::RemoveCard | EventEffect::UpgradeCard | EventEffect::TransformCard => {""",
    """            // §319：`falling` —— "Lose (a random <type> card)"。候选是**牌组里该类型的牌**，
            // 类型由内容池的 `PoolCard::kind` 决定（`rd-wasm` 的 `card_kind` 填的）。
            //
            // 一条候选都没有 ⇒ **拒绝**（`NoEligibleCard`），不是"什么都不做"：内容层面那条
            // 选项本来会被 `card_tag` 条件藏起来，所以走到这里说明条件与效果**对不上**，
            // 那正是应该响的地方。
            EventEffect::RemoveCardRandom(kind) => {
                let mut eligible = [0u8; MAX_RUN_DECK];
                let mut found = 0usize;
                for index in 0..self.deck_len as usize {
                    let id = self.deck[index].as_str();
                    let Some(facts) = pool.iter().find(|entry| entry.id == id) else {
                        continue;
                    };
                    if facts.kind == kind {
                        eligible[found] = index as u8;
                        found += 1;
                    }
                }
                if found == 0 {
                    return Err(RunError::NoEligibleCard);
                }
                let roll = self
                    .rng
                    .roll(RunStream::Event, found as u32)
                    .map_err(|_| RunError::EmptyRange)? as usize;
                self.remove_at(eligible[roll]);
            }
            EventEffect::RemoveCard | EventEffect::UpgradeCard | EventEffect::TransformCard => {""",
    'apply RemoveCardRandom')
write(STATE, t)
print('%s: patched' % STATE)

t = read(STREAMS)
t = sub_once(
    t,
    """    /// An effect that needs a deck index while the deck is empty. There is nothing to point at, so
    /// "pick a card" would be a screen with no way forward.
    DeckEmpty,
""",
    """    /// An effect that needs a deck index while the deck is empty. There is nothing to point at, so
    /// "pick a card" would be a screen with no way forward.
    DeckEmpty,
    /// §319: an effect that acts on "a card of type X" found no such card in the deck
    /// (`falling`'s `remove_card_random:power` in a deck with no Powers).
    ///
    /// Its own variant rather than `DeckEmpty`: the deck is not empty, the **content** is wrong
    /// (the option's `card_tag` condition should have hidden it). Reusing `DeckEmpty` would make
    /// the two indistinguishable in a log.
    NoEligibleCard,
""",
    'NoEligibleCard variant')
write(STREAMS, t)
print('%s: patched' % STREAMS)

t = read(WASM)
t = sub_once(
    t,
    """    rd_core::run_expr::RunFacts {
        gold: session.state.gold(),""",
    """    // §319：与 `deck` 逐位对应的类型名。来源是 `card_kind`（tag 位图的唯一读者）+
    // `CardKind::wire_name`（拼写的唯一一份），所以这里不再有第三份类型词表。
    let deck_tags: Vec<&str> = deck
        .iter()
        .map(|id| card_kind(content(), id).wire_name())
        .collect();
    rd_core::run_expr::RunFacts {
        gold: session.state.gold(),""",
    'wasm deck_tags build')
t = sub_once(
    t,
    """        deck,
        // §287：从卡的效果程序里读出"单次最高伤害"（`Wing Statue` 的条件要它）。""",
    """        deck,
        deck_tags: &deck_tags,
        // §287：从卡的效果程序里读出"单次最高伤害"（`Wing Statue` 的条件要它）。""",
    'wasm deck_tags field')
write(WASM, t)
print('%s: patched' % WASM)
