"""§331 Phase 2：`N'loth` —— "从手上任选一件遗物失去"（wiki 版是**两件随机候选**）。

wiki 原文（`slaythespire.wiki.gg/wiki/N'loth`）：

> It will only appear if the player has **at least 2 Relics**.
> "Relic A" and "Relic B" will be **randomly chosen from the player's currently held Relics**.
> `[Offer: Relic A]` Lose this relic. Obtain a special relic. … Rewards `N'loth's Gift`.

所以它**不是**"玩家任选一件"，而是"系统掷两件、玩家二选一"。这比"任选"便宜得多：
候选在**开事件那一刻**就定下来，两个选项是**固定**的，页面一行都不用改。

三块：

1. `EVND` 节点多一格 **`RelicOffer: N`**（这一段要掷几件候选；`0` = 没有）；
2. `rd-run` 存下这一掷（`event_offer_relics`），并让效果载荷 `relic_lose:@0` 解析成"第 0 件候选"；
3. `rd-wasm` 在 `begin_event` 之后掷（用 `RunStream::Event`，与事件抽取同一条流），
   并把选项标签里的 `{0}` / `{1}` 换成那件遗物的**显示名**。

⚠️ 标签替换放在 ABI 里而不是页面：页面已经按"读一段字节"渲染标签，替换在导出侧做，
页面零改动 —— 而"页面自己拼文案"正是 §274 记过的那类重复。
"""

import io

CONTENT_RS = 'kernel/rd-core/src/content.rs'
STATE_RS = 'kernel/rd-run/src/state.rs'
HASH_RS = 'kernel/rd-run/src/hash.rs'
RUN_RS = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ══ 1. content.rs：`EventStep.relic_offer` ═════════════════════════════════════
t = io.open(CONTENT_RS, encoding='utf-8').read()
t = sub(t, """    /// 选项（前 [`EventStep::count`] 条有效）。
    pub options: [EventOption<'a>; MAX_EVENT_OPTIONS],""",
        """    /// §331：这一段要掷几件**遗物候选**（`N'loth` 的两件）。`0` = 没有。
    pub relic_offer: u8,
    /// 选项（前 [`EventStep::count`] 条有效）。
    pub options: [EventOption<'a>; MAX_EVENT_OPTIONS],""",
        'step field')

t = sub(t, """            let mut step = EventStep::EMPTY;
            step.text = text;""",
        """            let mut step = EventStep::EMPTY;
            step.text = text;
            // §331：`RelicOffer` 与 `Effects` 一样落在 `extra` 格里（schema 没消费的键被打包）。
            step.relic_offer = crate::ir::NodeRef::new(self, row.extra())
                .int_field("RelicOffer")
                .ok()
                .flatten()
                .and_then(|count| u8::try_from(count).ok())
                .unwrap_or(0)
                .min(crate::content::MAX_EVENT_RELIC_OFFER as u8);""",
        'step read')
io.open(CONTENT_RS, 'w', encoding='utf-8', newline='\n').write(t)
print('content.rs: EventStep.relic_offer')

# ══ 2. rd-run：候选遗物 ═══════════════════════════════════════════════════════
t = io.open(STATE_RS, encoding='utf-8').read()

t = sub(t, """pub const ASCENDERS_BANE: &str = "ascenders_bane";""",
        """pub const ASCENDERS_BANE: &str = "ascenders_bane";

/// §331：一个事件最多掷几件**遗物候选**（`N'loth` 的两件）。
///
/// 与 `MAX_EVENT_OPTIONS` 分开：那是"一段有几个按钮"，这是"按钮里能引用几件候选"。
/// 取 2 是因为 wiki 只给了 A/B 两件；再大不是"更强的内容"，而是把事件屏当列表用。
pub const MAX_EVENT_RELIC_OFFER: usize = 2;""",
        'const')

t = sub(t, """    /// §286：事件把房间转成的那一场战斗的**档位**（`0` / `1` 普通 / `2` 精英）。""",
        """    /// §331：事件掷出的**遗物候选**（`N'loth` 的两件）。
    ///
    /// 为什么存下来而不是每次现掷：两个选项的**身份**由它决定（`relic_lose:@0`），
    /// 而"哪两件"必须在一个事件里**不变**（重渲染、存档、回放都要同一份答案）。
    pub fn event_offer_relic(&self, slot: usize) -> Option<&str> {
        if slot >= usize::from(self.event_offer_len) {
            return None;
        }
        let id = self.event_offer_relics[slot];
        if id.is_empty() {
            return None;
        }
        Some(id.as_str())
    }

    /// §331：写下第 `slot` 件候选（`rd-wasm` 在 `begin_event` 之后立刻调）。
    pub fn set_event_offer_relic(&mut self, slot: usize, id: &str) -> Result<(), RunError> {
        if slot >= MAX_EVENT_RELIC_OFFER {
            return Err(RunError::BadId);
        }
        let id = RunId::new(id).map_err(|_| RunError::BadId)?;
        // 重复的候选等于"两个选项一模一样"，那是内容/掷法的错 —— 响亮拒绝。
        for index in 0..usize::from(self.event_offer_len) {
            if index != slot && self.event_offer_relics[index] == id {
                return Err(RunError::BadId);
            }
        }
        self.event_offer_relics[slot] = id;
        if self.event_offer_len as usize <= slot {
            self.event_offer_len = (slot + 1) as u8;
        }
        Ok(())
    }

    /// §286：事件把房间转成的那一场战斗的**档位**（`0` / `1` 普通 / `2` 精英）。""",
        'accessors')

t = sub(t, """    tea_set_pending: bool,""",
        """    tea_set_pending: bool,
    /// §331：事件掷出的遗物候选（`N'loth`）。空 = 没有。
    event_offer_relics: [RunId; MAX_EVENT_RELIC_OFFER],
    /// 有效件数。
    event_offer_len: u8,""",
        'fields')

t = sub(t, """            tea_set_pending: false,""",
        """            tea_set_pending: false,
            event_offer_relics: [RunId::EMPTY; MAX_EVENT_RELIC_OFFER],
            event_offer_len: 0,""",
        'init')

t = sub(t, """        self.event = id;
        self.event_step = entry;""",
        """        self.event = id;
        self.event_step = entry;
        // §331：候选属于**一个**事件，开新事件就清掉。
        self.event_offer_relics = [RunId::EMPTY; MAX_EVENT_RELIC_OFFER];
        self.event_offer_len = 0;""",
        'begin_event clear')

t = sub(t, """                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                self.remove_relic(id)?;
            }
            EventEffect::GainRelic => {""",
        """                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                // §331：`@N` = "这一掷的第 N 件候选"（`N'loth`）。解析在**应用时**做，
                // 因为候选是开事件那一刻才有的（内容里写不出具体 id）。
                let owned;
                let id = if let Some(slot) = id.strip_prefix('@') {
                    let Ok(slot) = slot.parse::<usize>() else {
                        return Err(RunError::UnsupportedEventEffect);
                    };
                    let Some(candidate) = self.event_offer_relic(slot) else {
                        return Err(RunError::UnsupportedEventEffect);
                    };
                    owned = RunId::new(candidate).map_err(|_| RunError::BadId)?;
                    owned.as_str()
                } else {
                    id
                };
                self.remove_relic(id)?;
            }
            EventEffect::GainRelic => {""",
        'placeholder')
io.open(STATE_RS, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-run: event_offer_relics + @N')

# ══ 3. hash.rs：候选进指纹（它改变"以后会怎样"）═══════════════════════════════
t = io.open(HASH_RS, encoding='utf-8').read()
t = sub(t, """    writer.str("event_step=").str(state.event_step()).str("\\n");""",
        """    writer.str("event_step=").str(state.event_step()).str("\\n");
    // §331：事件掷出的遗物候选。它决定"点哪个按钮会失去哪件遗物"，所以是**会改变以后**的事实。
    writer.str("event_relics=");
    for slot in 0..rd_core::run_state_max_event_relic_offer() {
        match state.event_offer_relic(slot) {
            Some(id) => writer.str(id).str(","),
            None => writer.str("-,"),
        }
    }
    writer.str("\\n");""",
        'hash')
io.open(HASH_RS, 'w', encoding='utf-8', newline='\n').write(t)
print('hash.rs: candidates hashed')
