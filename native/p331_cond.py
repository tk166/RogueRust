"""§331 Phase 1：**事件级条件**（"这条事件出不出现"）。

现状：`EventTables` 的每一条只有 `MinFloor` / `MaxFloor` / `MinGold` 三个数，而 wiki 上有些
事件的**出现**本身就有条件：

* `The Moai Head` —— 只在 **HP ≤ 50%** 时出现（wiki: "This event only appears if the player's
  HP is below 50%"）；
* `Tomb of Lord Red Mask` —— 只在**持有 `red_mask`** 时出现；
* `N'loth` —— 只在**至少 2 件遗物**时出现（Phase 2 用它）。

现在这三条要么是"永远在池子里 + 选项被锁"，要么根本没做。前者不是等价物：它改变了 `?` 房的
**抽取分布**（一个用不上的事件仍然会占掉一次 `?` 房），而那正是"事件级"与"选项级"的区别。

做法：
1. `run_expr` 加一个数值 kind `relic_count`（`N'loth` 要"≥2 件"）；
2. `content.rs` 加 `event_pool_at_with_facts` —— 与 `event_pool_at` 同一段解码，多读一格
   `Requires`（`F_TERMLIST`，与选项的 `Requires` **同一个原子词表**），逐条求值；
   `event_pool_at` 原样保留（`None` facts = 不筛），存量调用与测试一个字都不用改；
3. `rd-wasm` 在 `?` 房改用带 facts 的那一个。
"""

import io

RUN_EXPR = 'kernel/rd-core/src/run_expr.rs'
CONTENT = 'kernel/rd-core/src/content.rs'
WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ── 1. `relic_count` kind ─────────────────────────────────────────────────────
t = io.open(RUN_EXPR, encoding='utf-8').read()
t = sub(t, """    // §321：`floor` —— 本幕内的层号（`mind_bloom` 的第三个选项按它换）。
    "floor",""",
        """    // §321：`floor` —— 本幕内的层号（`mind_bloom` 的第三个选项按它换）。
    "floor",
    // §331：`relic_count` —— 身上有几件遗物（`N'loth` 的"至少 2 件才出现"）。
    "relic_count",""", 'kinds')
t = sub(t, """const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension", "card_damage", "floor"];""",
        """const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension", "card_damage", "floor", "relic_count"];""",
        'numeric kinds')
t = sub(t, """            "deck_count" => i32::try_from(facts.deck.len()).unwrap_or(i32::MAX),""",
        """            "deck_count" => i32::try_from(facts.deck.len()).unwrap_or(i32::MAX),
            // §331：遗物件数。与 `deck_count` 同一个形状（"有几件"是数量，不是"有没有某一件"）。
            "relic_count" => i32::try_from(facts.relics.len()).unwrap_or(i32::MAX),""",
        'relic_count decide')
io.open(RUN_EXPR, 'w', encoding='utf-8', newline='\n').write(t)
print('run_expr: relic_count kind')

# ── 2. `event_pool_at_with_facts` ─────────────────────────────────────────────
t = io.open(CONTENT, encoding='utf-8').read()

OLD_SIG = """    #[must_use]
    pub fn event_pool_at(
        &'a self,
        pool: &str,
        floor: i32,
        gold: i32,
    ) -> Option<[&'a str; MAX_POOL_IDS]> {"""
NEW_SIG = """    #[must_use]
    pub fn event_pool_at(
        &'a self,
        pool: &str,
        floor: i32,
        gold: i32,
    ) -> Option<[&'a str; MAX_POOL_IDS]> {
        self.event_pool_at_with_facts(pool, floor, gold, None)
    }

    /// §331：与 [`Self::event_pool_at`] 同一段解码，多筛一格 **`Requires`**（事件级条件）。
    ///
    /// `facts = None` ⇒ 不筛（存量行为，`event_pool_at` 就是这么调的）。
    ///
    /// ⚠️ 为什么条件求值放在**这里**而不是调用方：`Requires` 的原子词表只有一份
    /// （[`crate::run_expr::option_is_available`]），而"池条目的 `Requires`"与"选项的 `Requires`"
    /// 是**同一个字段名、同一串原子**。放在两处就会有两份"什么算成立"。
    #[must_use]
    pub fn event_pool_at_with_facts(
        &'a self,
        pool: &str,
        floor: i32,
        gold: i32,
        facts: Option<&crate::run_expr::RunFacts<'_>>,
    ) -> Option<[&'a str; MAX_POOL_IDS]> {"""
t = sub(t, OLD_SIG, NEW_SIG, 'signature')

OLD_DECODE = """            let mut min_gold = 0i32;"""
NEW_DECODE = """            let mut min_gold = 0i32;
            // §331：事件级条件（`F_TERMLIST`，与选项的 `Requires` 同一串原子）。
            let mut requires = crate::content::ABSENT16;"""
t = sub(t, OLD_DECODE, NEW_DECODE, 'requires var')

OLD_FIELDS = """                } else if sub_name == "MinGold" && sub.kind() == F_INT {
                    min_gold = slot_int(element_term.slot(offset)?);
                }"""
NEW_FIELDS = """                } else if sub_name == "MinGold" && sub.kind() == F_INT {
                    min_gold = slot_int(element_term.slot(offset)?);
                } else if sub_name == "Requires" && sub.kind() == F_TERMLIST {
                    requires = element_term.slot(offset)?;
                }"""
t = sub(t, OLD_FIELDS, NEW_FIELDS, 'requires field')

OLD_FILTER = """            if id.is_empty()
                || floor < min_floor
                || (max_floor != 0 && floor > max_floor)
                || gold < min_gold
            {
                continue;
            }"""
NEW_FILTER = """            if id.is_empty()
                || floor < min_floor
                || (max_floor != 0 && floor > max_floor)
                || gold < min_gold
            {
                continue;
            }
            // §331：事件级条件。读不出来 ⇒ **整池拒绝**（`None`）而不是"这条放行" ——
            // 条件坏了却让事件照常出现，是"看起来在跑"的死内容里最难发现的一种。
            if let Some(facts) = facts {
                if requires != crate::content::ABSENT16
                    && !crate::run_expr::option_is_available(self, requires, facts).ok()?
                {
                    continue;
                }
            }"""
t = sub(t, OLD_FILTER, NEW_FILTER, 'filter')
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(t)
print('content.rs: event_pool_at_with_facts')

# ── 3. rd-wasm 在 `?` 房带上 facts ────────────────────────────────────────────
t = io.open(WASM, encoding='utf-8').read()
OLD_PICK = """        let gold = session.state.gold();
        let Some(pool) = image.event_pool_at(pool_name, floor, gold) else {"""
NEW_PICK = """        let gold = session.state.gold();
        // §331：事件级条件（"这条事件出不出现"）要在**掷之前**参与筛选 —— 与楼层/金币同一个
        // 筛子，所以"池子里有几个"仍然不改变筛掉几个之后的随机流位置。
        let relics: Vec<&str> = session.state.relics().iter().map(|id| id.as_str()).collect();
        let deck: Vec<&str> = session.state.deck().iter().map(|id| id.as_str()).collect();
        let deck_tags: Vec<&str> = deck
            .iter()
            .map(|id| card_kind(image, id).wire_name())
            .collect();
        let facts = run_facts(session, &relics, &deck, &deck_tags);
        let Some(pool) = image.event_pool_at_with_facts(pool_name, floor, gold, Some(&facts))
        else {"""
t = sub(t, OLD_PICK, NEW_PICK, 'wasm pool call')
io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm: ? room filters by Requires')
