"""§320 第二半 —— 应用、收尾、访问器、存档、指纹。"""

import io

STATE = 'kernel/rd-run/src/state.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d occurrences' % (label, n)
    return t.replace(old, new)


t = io.open(STATE, encoding='utf-8').read()

# ── 1. 应用：抽候选（事务内，失败即回滚）──────────────────────────────────────────
t = sub(t, """            EventEffect::RemoveCardRandom(kind) => {""",
        """            // §320：`[Read]` / `[Recall]` —— 抽 `n` 张**互不相同**的候选摊开。
            //
            // 走 `RunStream::Event`（与 `falling` 的随机删牌同一条流：这是一段事件的掷骰，
            // 不该消耗战斗的 `(seed, step)`）。候选**只在这里抽一次**，之后摊在
            // `event_offer` 里等玩家选 —— 重渲染不会重新掷。
            EventEffect::OfferCards(count, filter) => {
                let mut candidates = [0u8; MAX_POOL];
                let mut found = 0usize;
                for (index, card) in pool.iter().enumerate() {
                    if !filter.admits(card) {
                        continue;
                    }
                    if found >= MAX_POOL {
                        return Err(RunError::PoolTooLarge {
                            pool: found + 1,
                            max: MAX_POOL,
                        });
                    }
                    candidates[found] = index as u8;
                    found += 1;
                }
                let wanted = usize::from(count);
                if found < wanted {
                    // 池子凑不出它承诺的张数 ⇒ 拒绝（不是"少给几张"）。内容门在
                    // `sts_content_check` 里也用同一条规则先拦一次。
                    return Err(RunError::PoolTooSmall {
                        pool: found,
                        need: wanted,
                    });
                }
                // 不放回抽样：把这个子集洗一遍再取前 `wanted` 张。洗的是**池子下标**，
                // 所以同一张牌不会出现两次（`draw_distinct` 的既有语义）。
                self.rng
                    .shuffle(RunStream::Event, &mut candidates[..found]);
                for slot in 0..wanted {
                    let card = &pool[candidates[slot] as usize];
                    self.event_offer[slot] = RunId::new(card.id).map_err(|_| RunError::BadId)?;
                }
                for slot in wanted..MAX_EVENT_OFFER {
                    self.event_offer[slot] = RunId::EMPTY;
                }
                self.event_offer_len = count;
            }
            EventEffect::RemoveCardRandom(kind) => {""",
        'apply OfferCards')

# ── 2. `resolve_event_effects`：候选占的是同一个"待答"位置 ─────────────────────────
t = sub(t, """        let before = *self;
        let mut follow: Option<DeckChange> = None;""",
        """        let before = *self;
        // §320：上一轮可能已经有过一段候选（正常情况下没有：取走一张就清空）。
        // 进这一段之前先清，否则"漏清"会表现成"上一段的候选又冒出来"。
        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        self.event_offer_len = 0;
        let mut follow: Option<DeckChange> = None;""",
        'clear offer before apply')

t = sub(t, """        // §286：这一段的选项是**一场战斗** ⇒ 事件收尾、房间**不**结算（战斗结算它）。
        if fight != 0 {
            if follow.is_some() {""",
        """        // §320：候选与改牌问句**抢同一个位置**（`pending` 只有一个），所以两个都有
        // 或者"要问 + 要开打"都是内容错误 —— 与两条改牌效果同一条规矩。
        if self.event_offer_len > 0 && follow.is_some() {
            *self = before;
            return Err(RunError::TwoDeckChanges);
        }
        // §286：这一段的选项是**一场战斗** ⇒ 事件收尾、房间**不**结算（战斗结算它）。
        if fight != 0 {
            if self.event_offer_len > 0 {
                *self = before;
                return Err(RunError::TwoDeckChanges);
            }
            if follow.is_some() {""",
        'offer vs fight guard')

t = sub(t, """        match follow {
            Some(change) => {
                self.event_follow = Some(change);""",
        """        // §320：候选列表是这一段的**待答**。与改牌那条完全同一条尾巴（`event_next`），
        // 所以"三次 Recall"是内容把三段 `Next` 串起来，不需要第二个状态机。
        if self.event_offer_len > 0 {
            self.event_next = next_id;
            self.pending = Pending::EventOffer;
            return Ok(());
        }
        match follow {
            Some(change) => {
                self.event_follow = Some(change);""",
        'offer pending branch')

# ── 3. 访问器 + 取牌 ─────────────────────────────────────────────────────────────
t = sub(t, """    pub fn pick_event_card(""",
        """    /// §320：这一段的候选有几张（没有候选 ⇒ `0`）。
    #[must_use]
    pub const fn event_offer_len(&self) -> usize {
        self.event_offer_len as usize
    }

    /// §320：候选槽 `slot` 的牌 id（越界或空槽 ⇒ `None`）。
    #[must_use]
    pub fn event_offer_card(&self, slot: usize) -> Option<&str> {
        if slot >= self.event_offer_len as usize {
            return None;
        }
        Some(self.event_offer[slot].as_str())
    }

    /// §320：从候选里取走一张（`The Library` 的 20 选 1、`Sensory Stone` 的每次 Recall）。
    ///
    /// 收尾与 [`Self::pick_event_card`] 逐字相同：有 `event_next` 就去下一段（房间不结算），
    /// 没有就结算这一段。**不同的一点**：这里要把那一行从池子里找出来再交给 `push_card` ——
    /// 三个蛋（`molten_egg` 等）要在**进牌组那一刻**生效，而它需要 `PoolCard`（类型 + `+` 行）。
    pub fn pick_event_offer(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::EventOffer {
            return Err(RunError::WrongPhase);
        }
        if slot >= self.event_offer_len as usize {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        let id = self.event_offer[slot].as_str();
        let Some(row) = pool.iter().find(|card| card.id == id).copied() else {
            return Err(RunError::NoSuchCard);
        };
        // 牌组满了 ⇒ `push_card` 的 `Capacity`（响亮，不静默丢牌）。
        self.push_card(row)?;
        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        self.event_offer_len = 0;
        if !self.event_next.as_str().is_empty() {
            self.event_step = self.event_next;
            self.event_next = RunId::EMPTY;
            self.pending = Pending::Event;
            return Ok(());
        }
        self.pending = Pending::None;
        self.event_step = RunId::EMPTY;
        self.mark_resolved();
        Ok(())
    }

    pub fn pick_event_card(""",
        'pick_event_offer')

io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs part 2 ok')

# ── 4. 存档 ──────────────────────────────────────────────────────────────────────
t = io.open(ARCHIVE, encoding='utf-8').read()
t = sub(t, """    writer.byte(match state.event_follow {
        None => u8::MAX,
        Some(change) => deck_change_to_u8(change),
    })?;""",
        """    writer.byte(match state.event_follow {
        None => u8::MAX,
        Some(change) => deck_change_to_u8(change),
    })?;
    // §320：事件候选列表（`0` = 没有候选，也是绝大多数时候）。
    writer.byte(state.event_offer_len() as u8)?;
    for slot in 0..state.event_offer_len() {
        let id = state.event_offer_card(slot).unwrap_or("");
        writer.id(RunId::new(id).map_err(|_| ArchiveError::BadField("event_offer"))?)?;
    }""",
        'archive write offer')

t = sub(t, """    restored.event_follow = event_follow;""",
        """    restored.event_follow = event_follow;
    // §320：候选表（`len` 之后恒为空，与 `deck` 的尾槽同一条纪律 —— 读的时候也验一遍）。
    let offer_len = offer_len as usize;
    if offer_len > MAX_EVENT_OFFER {
        return Err(ArchiveError::BadField("event_offer_len"));
    }
    for slot in 0..offer_len {
        let id = offer_ids[slot];
        if id.as_str().is_empty() {
            return Err(ArchiveError::BadField("event_offer"));
        }
        restored.event_offer[slot] = id;
    }""",
        'archive read offer')
io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(t)
print('archive.rs patched (needs the read side wired)')

# ── 5. 指纹 ──────────────────────────────────────────────────────────────────────
t = io.open(HASH, encoding='utf-8').read()
t = sub(t, """    writer.str("event_follow=").str(deck_change_code(state.event_follow())).str("\\n");""",
        """    writer.str("event_follow=").str(deck_change_code(state.event_follow())).str("\\n");
    // §320：事件候选列表。**不写**会让"同一局的两条分支"（20 选 1 的不同候选）哈希成同一串 ——
    // 而候选是玩家看得见的局面（选哪张由它决定）。
    writer.str("event_offer=").u32(state.event_offer_len() as u32).str("\\n");
    for slot in 0..state.event_offer_len() {
        writer.str("of=").str(state.event_offer_card(slot).unwrap_or("")).str("\\n");
    }""",
        'hash offer')
io.open(HASH, 'w', encoding='utf-8', newline='\n').write(t)
print('hash.rs patched')
