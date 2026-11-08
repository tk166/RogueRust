"""§308：`RunState` 的存档/指纹字段清点（审阅报告 §2 的落地）。

报告列了 5 组；`native/check_state_fields.py` 穷尽遍历结构体字段之后是 **18 个字段**
（17 个两边都缺 + `event_step` 只在指纹里）。这一轮补全，并把"下一个字段又只加在结构体里"
变成一道会红的闸门。

同时修两个连带缺陷（清点时撞见的，都属于"同一份事实两种存法"）：
1. `remove_deck_card` 清了 `deck` 的尾槽却**没清 `marks` 的尾槽** ⇒ 尾槽留着被删牌的成长；
2. `push_card` 写 `deck[slot]` 却**没清 `marks[slot]`** ⇒ 新牌会继承上一位的 mark
   （`Ritual Dagger` 删掉之后再拿一张，两张共享成长）。§253 修过"删牌时 mark 跟着走"，
   但没修"加牌时它是全新的"。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # ═══ 1. state.rs：mark 的两处遗留 ═════════════════════════════════════════════════════
    patch(STATE, '''        // **`len` 之后必须是 EMPTY**（REVIEW P1，§161.10）。
        self.deck[self.deck_len as usize - 1] = RunId::EMPTY;
        self.deck_len -= 1;''',
'''        // **`len` 之后必须是 EMPTY**（REVIEW P1，§161.10）。
        self.deck[self.deck_len as usize - 1] = RunId::EMPTY;
        // §308：`marks` 的尾槽同理 —— 否则被删那张牌的成长留在尾槽，下一张**加进来**的牌
        // 会继承它（`push_card` 只写 `deck[slot]`）。这条在存档里也是硬要求：marks 只写
        // 活动前缀，尾槽有值就意味着"存档丢了数据"。
        self.marks[self.deck_len as usize - 1] = RunMark::NONE;
        self.deck_len -= 1;''')

    patch(STATE, '''        self.deck[slot] = chosen;
        self.deck_len += 1;''',
'''        // §308：新牌**没有**跨场历史。`remove_deck_card` 已经把尾槽清干净了，但 `slot` 可能
        // 不是尾槽（比如 Duplicate 在一张带 mark 的牌前面插一张是不可能的 —— 这里是**防御**）：
        // 无论哪种，写牌位的同时把 mark 归零，才是"一张新牌"。
        self.marks[slot] = RunMark::NONE;
        self.deck[slot] = chosen;
        self.deck_len += 1;''')

    # ═══ 2. state.rs：那句话是错的（两个指纹混为一谈）════════════════════════════════════
    patch(STATE, '''/// ⚠️ 它**不进 run hash**（`hash.rs` 逐字段写）：参考的运行层没有这个概念，而那个指纹要与
/// 参考对齐。与 §201 的 `CombatState.gold_carried_away` 同一条裁决。''',
'''/// §308：**它进 run hash**。旧版本这里写着"不进" —— 那是把两个指纹混为一谈：`hash_golden`
/// （参考引擎逐字节复刻，参考的运行层确实没有这个概念）与 `hash.rs`（**我们自己**的行动回放
/// 指纹，判据是"同一串动作之后同一局"）。后者只要一个字段影响**未来行为**就必须覆盖它，
/// 否则"两局哈希相同"这句话会漏掉"牌还是那张牌、但是伤害不同"。
/// 与 §201 的 `CombatState.gold_carried_away` 是**不同**的裁决：那个字段在战斗指纹里确实
/// 没有消费者（跨场结算在 run 层）。''')

    # ═══ 3. state.rs：缺的访问器（hash.rs 是兄弟模块，读不到私有字段）════════════════════
    patch(STATE, '''    /// §303：`wing_boots` 还能飞几次''',
'''    /// §308：与 `deck` **同下标**的每副本数据（只到活动前缀）。
    ///
    /// 给 `hash.rs` 用的：跨场的 `Ritual Dagger` 成长必须进指纹，否则"同一串动作"可以长出
    /// 两种牌组（伤害不同、哈希相同）。
    #[must_use]
    pub fn marks(&self) -> &[RunMark] {
        &self.marks[..self.deck_len as usize]
    }

    /// §308：这一幕已经倒下几个 Boss（`A20` 的第三幕双 Boss 进度）。进存档与指纹：
    /// 回档之后"还欠不欠第二场"是玩家能看见的东西。
    #[must_use]
    pub const fn bosses_fought(&self) -> u8 {
        self.bosses_fought
    }

    /// §308：战斗之后要回到的事件段（空 = 战斗结算整个房间）。
    #[must_use]
    pub const fn event_resume(&self) -> RunId {
        self.event_resume
    }

    /// §308：这一段选完之后要去的那一段（在等一次牌组编辑时先记在这里）。
    #[must_use]
    pub const fn event_next(&self) -> RunId {
        self.event_next
    }

    /// §308：下一场战斗的金币加成 / 定数 / 不掉遗物 / 指名遗物 / 稀有度锁 / 独立药水概率。
    ///
    /// 六个都**只活到下一场战斗**，但"下一场"是从存档之后开始的那一场 —— 所以它们必须
    /// 跟着存档走，否则 `Dead Adventurer` 的金币加成与"这件遗物已经搜到了"都会消失。
    #[must_use]
    pub const fn fight_gold_bonus(&self) -> i16 {
        self.fight_gold_bonus
    }
    /// §308：同上。
    #[must_use]
    pub const fn fight_gold_set(&self) -> i16 {
        self.fight_gold_set
    }
    /// §308：同上。
    #[must_use]
    pub const fn fight_no_relic(&self) -> bool {
        self.fight_no_relic
    }
    /// §308：同上。
    #[must_use]
    pub const fn fight_relic_rarity(&self) -> u8 {
        self.fight_relic_rarity
    }
    /// §308：同上。
    #[must_use]
    pub const fn fight_extra_relic(&self) -> u8 {
        self.fight_extra_relic
    }
    /// §308：同上。
    #[must_use]
    pub const fn fight_relic(&self) -> RunId {
        self.fight_relic
    }
    /// §308：同上（`255` = 不覆盖）。
    #[must_use]
    pub const fn fight_potion_chance(&self) -> u8 {
        self.fight_potion_chance
    }

    /// §303：`wing_boots` 还能飞几次''')

    # ═══ 4. state.rs：不变量（尾槽与 A20 进度）════════════════════════════════════════════
    patch(STATE, '''        if self.rarity_offset < RARITY_OFFSET_START || self.rarity_offset > RARITY_OFFSET_CAP {
            return Err(RunError::Invariant("rarity_offset is outside its pity band"));
        }''',
'''        if self.rarity_offset < RARITY_OFFSET_START || self.rarity_offset > RARITY_OFFSET_CAP {
            return Err(RunError::Invariant("rarity_offset is outside its pity band"));
        }
        // §308：`marks` 只允许在活动前缀里有值。尾槽有 mark = "被删那张牌的成长还留在原地"，
        // 而 `push_card` 的下一次写入会让新牌**继承**它。
        for slot in self.deck_len as usize..MAX_RUN_DECK {
            if !self.marks[slot].is_none() {
                return Err(RunError::Invariant("a per-copy mark outlived its card"));
            }
        }
        // §308：一幕里最多倒下一个 Boss（`A20` 的第三幕要打两个，但计数只到 1 就换幕）。
        if self.bosses_fought > 1 {
            return Err(RunError::Invariant("bosses_fought must be 0 or 1"));
        }''')

    # ═══ 5. archive.rs：版本 + 新增字段 ═════════════════════════════════════════════════════
    patch(ARCHIVE, 'const VERSION: u8 = 10;', 'const VERSION: u8 = 11;  // §308：事件链 + 宝箱计数器 + 每副本 mark。')

    patch(ARCHIVE, '''    writer.byte(state.pickup_add())?;
    writer.byte(state.pickup_offer().len() as u8)?;
    for card in state.pickup_offer() {
        writer.id(*card)?;
    }

    writer.byte(state.deck_len)?;
    for card in state.deck.iter().take(state.deck_len as usize) {
        writer.id(*card)?;
    }''',
'''    writer.byte(state.pickup_add())?;
    writer.byte(state.pickup_offer().len() as u8)?;
    for card in state.pickup_offer() {
        writer.id(*card)?;
    }

    // ══ §308：审阅报告 §2 查出来的漏网字段。**这一整块的理由是同一个**：它们都影响
    // "存档之后的那一局"（事件走到第几段、宝箱还欠几件、A20 还欠不欠第二个 Boss、
    // 下一场战斗的奖励怎么算）。判据不是"我记得加"，而是 `native/check_state_fields.py`
    // 穷尽遍历 `RunState` 的字段表 —— 少一个就红。
    writer.id(state.event_step)?;
    writer.id(state.event_resume)?;
    writer.id(state.event_next)?;
    writer.id(state.event_fight_pool)?;
    writer.id(state.fight_relic)?;
    writer.byte(state.event_fight)?;
    writer.byte(state.bosses_fought)?;
    writer.byte(state.chest_extra)?;
    writer.byte(state.chest_empty)?;
    writer.byte(state.pickup_relics)?;
    writer.byte(state.pickup_potions)?;
    writer.byte(state.fight_relic_rarity)?;
    writer.byte(state.fight_extra_relic)?;
    writer.byte(state.fight_potion_chance)?;
    writer.int(i32::from(state.fight_gold_bonus))?;
    writer.int(i32::from(state.fight_gold_set))?;
    writer.byte(u8::from(state.fight_no_relic))?;

    writer.byte(state.deck_len)?;
    for card in state.deck.iter().take(state.deck_len as usize) {
        writer.id(*card)?;
    }
    // §308：每副本数据，**只写活动前缀**。尾槽必须为空这条由 `check_invariants` 保证 ——
    // 于是"前缀外有值"会是 `Invariant`，而不是"存档悄悄少了一格"。
    for mark in state.marks.iter().take(state.deck_len as usize) {
        writer.id(mark.key)?;
        writer.int(mark.value)?;
    }''')

    # ═══ 6. archive.rs：读侧 ═══════════════════════════════════════════════════════════════
    patch(ARCHIVE, '''    let mut deck = [RunId::EMPTY; MAX_RUN_DECK];
    let deck_len = reader.byte()? as usize;
    if deck_len > MAX_RUN_DECK {
        return Err(ArchiveError::BadField("deck"));
    }
    for slot in 0..deck_len {
        deck[slot] = reader.id()?;
    }''',
'''    // §308：与写侧同序 —— 事件链 / 宝箱计数器 / 下场的奖励覆盖。
    let event_step = reader.id()?;
    let event_resume = reader.id()?;
    let event_next = reader.id()?;
    let event_fight_pool = reader.id()?;
    let fight_relic = reader.id()?;
    let event_fight = reader.byte()?;
    let bosses_fought = reader.byte()?;
    let chest_extra = reader.byte()?;
    let chest_empty = reader.byte()?;
    let pickup_relics = reader.byte()?;
    let pickup_potions = reader.byte()?;
    let fight_relic_rarity = reader.byte()?;
    let fight_extra_relic = reader.byte()?;
    let fight_potion_chance = reader.byte()?;
    let fight_gold_bonus = reader.int()? as i16;
    let fight_gold_set = reader.int()? as i16;
    let fight_no_relic = reader.byte()?;
    // §308：容量是语义 —— 读到 2 是**存档坏了**，不是"夹到 1"。
    if bosses_fought > 1 {
        return Err(ArchiveError::BadField("bosses_fought"));
    }

    let mut deck = [RunId::EMPTY; MAX_RUN_DECK];
    let deck_len = reader.byte()? as usize;
    if deck_len > MAX_RUN_DECK {
        return Err(ArchiveError::BadField("deck"));
    }
    for slot in 0..deck_len {
        deck[slot] = reader.id()?;
    }
    // §308：每副本 mark（与 deck 同下标、同长度）。
    let mut marks = [RunMark::NONE; MAX_RUN_DECK];
    for slot in 0..deck_len {
        marks[slot] = RunMark {
            key: reader.id()?,
            value: reader.int()?,
        };
    }''')

    # ═══ 7. archive.rs：还原赋值 ═══════════════════════════════════════════════════════════
    patch(ARCHIVE, '''    restored.deck = deck;
    restored.deck_len = deck_len as u8;''',
'''    restored.deck = deck;
    restored.deck_len = deck_len as u8;
    // §308
    restored.marks = marks;
    restored.event_step = event_step;
    restored.event_resume = event_resume;
    restored.event_next = event_next;
    restored.event_fight_pool = event_fight_pool;
    restored.event_fight = event_fight;
    restored.bosses_fought = bosses_fought;
    restored.chest_extra = chest_extra;
    restored.chest_empty = chest_empty;
    restored.pickup_relics = pickup_relics;
    restored.pickup_potions = pickup_potions;
    restored.fight_relic = fight_relic;
    restored.fight_relic_rarity = fight_relic_rarity;
    restored.fight_extra_relic = fight_extra_relic;
    restored.fight_potion_chance = fight_potion_chance;
    restored.fight_gold_bonus = fight_gold_bonus;
    restored.fight_gold_set = fight_gold_set;
    restored.fight_no_relic = fight_no_relic != 0;''')

    # ═══ 8. hash.rs：补齐 ═══════════════════════════════════════════════════════════════════
    patch(HASH, '''    writer
        .str("last_encounter=")''',
'''    // ══ §308：审阅报告 §2 的另一半 —— 上面那些字段进了存档，**也必须进指纹**。
    // 理由只有一个：它们都改变"以后会怎样"。`Ritual Dagger` 的成长尤其明显：
    // 不入指纹的话，"同一串动作"能长出两种牌组（伤害不同、哈希相同），
    // 而回放判据正是"同一串动作 ⇒ 同一局"。
    writer.str("bosses_fought=").u32(u32::from(state.bosses_fought())).str("\\n");
    writer
        .str("chest=")
        .u32(u32::from(state.chest_extra_remaining()))
        .str("/")
        .u32(u32::from(state.chest_empty_remaining()))
        .str("\\n");
    writer
        .str("pickup_owed=")
        .u32(u32::from(state.pickup_relics()))
        .str("/")
        .u32(u32::from(state.pickup_potions()))
        .str("\\n");
    writer.str("event_resume=").str(state.event_resume()).str("\\n");
    writer.str("event_next=").str(state.event_next()).str("\\n");
    writer
        .str("event_fight=")
        .u32(u32::from(state.event_fight()))
        .str("/")
        .str(state.event_fight_pool())
        .str("\\n");
    writer
        .str("fight_next=")
        .i32(i32::from(state.fight_gold_bonus()))
        .str("/")
        .i32(i32::from(state.fight_gold_set()))
        .str("/")
        .u32(u32::from(state.fight_relic_rarity()))
        .str("/")
        .u32(u32::from(state.fight_extra_relic()))
        .str("/")
        .u32(u32::from(state.fight_potion_chance()))
        .str("/")
        .str(state.fight_relic())
        .str("/")
        .u32(u32::from(u8::from(state.fight_no_relic())))
        .str("\\n");
    // 每副本 mark：与 `deck` 同下标。**牌名 + 值**都写 —— 只写值的话，"5 点成长"与
    // "另一条计数器的 5"会哈希成同一个。
    for mark in state.marks() {
        writer.str("m=").str(mark.key.as_str()).str(",").i32(mark.value).str("\\n");
    }
    writer
        .str("last_encounter=")''')

    print('all patches applied')


main()
