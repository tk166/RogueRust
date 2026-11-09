"""§319 —— `falling` 的两个内核件：

1. `RunFacts::deck_tags` + 条件原子 `card_tag`（"牌组里有/没有一张 <tag> 牌"）。
   wiki 的 Falling 有三个选项，**各自按类型上锁**（"if the player has no Powers for the
   [Channel] option, it is replaced with [Locked] Requires: Power Card"）—— 那正是
   `rd_core::run_expr` 已经在做的"选项条件"，只是缺一个"按类型数牌组"的事实。
2. `EventEffect::RemoveCardRandom(CardKind)` —— "Lose (a **random** Skill)"。
   ⚠️ wiki 明确是**随机**删，不是玩家挑：`[Land] Lose (a random Skill)`。
   所以它**不是** `DeckChange`（那条路会进 `Pending::EventCard` 让人选一张），
   而是应用效果时就地掷一次。

两处的词表都只有一份：`CardKind::wire_name` / `from_wire` 同时供
`remove_card_random:<kind>` 的解析与 `rd-wasm` 填 `deck_tags` 用。
"""

import io
import re

RUN_EXPR = 'kernel/rd-core/src/run_expr.rs'
CONTENT = 'kernel/rd-core/src/content.rs'
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


# ── 1. `RunFacts::deck_tags` ────────────────────────────────────────────────────────────
t = read(RUN_EXPR)
t = sub_once(
    t,
    """    /// 牌组里的卡 id（重复的算多次：`deck_count` 数的是**张数**）。
    pub deck: &'a [&'a str],
""",
    """    /// 牌组里的卡 id（重复的算多次：`deck_count` 数的是**张数**）。
    pub deck: &'a [&'a str],
    /// §319：与 [`Self::deck`] **逐位对应**的类型名（`attack` / `skill` / `power` / `curse` /
    /// `status` / `other`），给条件原子 `card_tag` 用（`Falling` 的三个选项各自按类型上锁）。
    ///
    /// 为什么由调用方给：类型是**内容**的事（tag 位图 → `CardKind` 的映射在 `rd-wasm` 的
    /// `card_kind` 里，且 `CardKind::wire_name` 是唯一的拼写）。这一层只数"有几个"。
    pub deck_tags: &'a [&'a str],
""",
    'RunFacts deck_tags field')

t = sub_once(
    t,
    """    // §287：`card_damage` —— "牌组里有一张**单次** ≥ N 伤害的牌"（`Wing Statue` 的 `[Destroy]`）。
    "card_damage",
""",
    """    // §287：`card_damage` —— "牌组里有一张**单次** ≥ N 伤害的牌"（`Wing Statue` 的 `[Destroy]`）。
    "card_damage",
    // §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自按类型上锁）。
    "card_tag",
""",
    'KINDS card_tag')

t = sub_once(
    t,
    """        "card" => facts.deck.contains(&id),
""",
    """        "card" => facts.deck.contains(&id),
        // §319：按**类型**。`deck_tags` 与 `deck` 逐位对应，所以"有一张"就是"表里有"。
        "card_tag" => facts.deck_tags.contains(&id),
""",
    'decide card_tag')

# 测试：`every_kind_answers_both_sides` —— 这条判据是"每种 kind 两侧都测"的穷尽表，
# 新 kind 必须在这里成对出现（否则"某个 kind 恒真"在真内容上永远不会红）。
t = sub_once(
    t,
    """        let deck = ["strike", "defend", "strike", "regret"];
        let relics = ["golden_idol"];
        let facts = RunFacts {
            gold: 100,
            health: 40,
            health_max: 80,
            ascension: 10,
            relics: &relics,
            deck: &deck,
""",
    """        let deck = ["strike", "defend", "strike", "regret"];
        let relics = ["golden_idol"];
        // §319：与 `deck` 逐位对应（`strike`/`strike` 攻击、`defend` 技能、`regret` 诅咒）。
        let tags = ["attack", "skill", "attack", "curse"];
        let facts = RunFacts {
            gold: 100,
            health: 40,
            health_max: 80,
            ascension: 10,
            relics: &relics,
            deck: &deck,
            deck_tags: &tags,
""",
    'facts in every_kind_answers_both_sides')

t = sub_once(
    t,
    """            ("card", "lacks", 0, "strike", false),
        ];
""",
    """            ("card", "lacks", 0, "strike", false),
            // §319：按**类型**。牌组里有攻击/技能/诅咒，**没有能力** —— `power` 那一对
            // 正是 `Falling` 的 `[Channel]` 在真内容里的处境（本内容 0 张 power 牌）。
            ("card_tag", "has", 0, "attack", true),
            ("card_tag", "has", 0, "power", false),
            ("card_tag", "lacks", 0, "power", true),
            ("card_tag", "lacks", 0, "attack", false),
            // 大小写与陌生名字都**不成立**（不是"退回成 any"）。
            ("card_tag", "has", 0, "Attack", false),
            ("card_tag", "has", 0, "", false),
        ];
""",
    'card_tag cases')

# 其余 `RunFacts` 字面量（`content.rs` 三个 + `run_expr.rs` 一个 helper）补上空的 tags。
for path in (RUN_EXPR, CONTENT):
    t2 = read(path)
    pat = re.compile(r'(\n(\s+))max_hit_damage:')
    count = len(pat.findall(t2))
    t2, n = pat.subn(lambda m: '%sdeck_tags: &[],%smax_hit_damage:' % (m.group(1), m.group(1)), t2)
    assert n == count, 'deck_tags insertion: %d of %d' % (n, count)
    write(path, t2)
    print('%s: deck_tags added to %d literals' % (path, n))

# ── 2. `CardKind::wire_name` / `from_wire` ────────────────────────────────────────────
t = read(STATE)
t = sub_once(
    t,
    """/// A card as the reward roll sees it.
pub struct PoolCard<'a> {""",
    """impl CardKind {
    /// §319：内容/线缆上的拼写（`attack` / `skill` / `power` / `curse` / `status` / `other`）。
    ///
    /// **唯一一份**：`remove_card_random:<kind>` 的解析、`rd-wasm` 填 `RunFacts::deck_tags`、
    /// 以及条件原子 `card_tag` 的 `Id` 都用它。抄第二份的代价是"事件能删、条件认不出"，
    /// 而这种漂不会让任何判据变红（见 §161 的 `known` 表那次）。
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
pub struct PoolCard<'a> {""",
    'CardKind impl')

# ── 3. `EventEffect::RemoveCardRandom` ───────────────────────────────────────────────
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
""",
    'parse remove_card_random')

# 应用：就地在牌组里按类型挑候选，掷一次，删掉。
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

# ── 4. 新的错误变体 ──────────────────────────────────────────────────────────────────
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

# ── 5. `rd-wasm` 填 `deck_tags` ─────────────────────────────────────────────────────
t = read(WASM)
t = sub_once(
    t,
    """    let facts = run_facts(session, &relics, &deck);""",
    """    let facts = run_facts(session, &relics, &deck);""",
    'noop marker') if False else t
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

print('kernel patched')
