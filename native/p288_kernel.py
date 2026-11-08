"""§288 内核：`After`（打完**回到事件**）+ 奖励覆盖（`fight_gold_set` / `fight_relic_rarity` /
`fight_extra_relic`）+ 事件池的楼层门槛。

## ① `After`：战斗之后回到事件

§286 的 `Fight` 让**战斗结算房间**（`Dead Adventurer`：打完事件就结束）。`The Colosseum`
相反：第一场打完要**回到事件**继续选 `[COWARDICE]` / `[VICTORY]`。所以选项多一格：

    { Label: "Fight", Fight: "monster", Encounter: "ColosseumSlavers", After: "the_colosseum.after" }

`After` 存在时：事件**不收尾**（`event` 留着、`event_step` 清空、房间不结算），
`event_resume` 记住回哪一段。打赢之后 `resume_event_after_fight()` 把事件重新摆到那一段，
并且**不发战斗奖励** —— wiki："This fight gives no rewards."（奖励就是事件继续）。

## ② 奖励覆盖（`The Colosseum` 的 VICTORY）

wiki：`100 Gold, 1 Rare Relic, 1 Uncommon Relic, a card reward, sometimes a Potion`。
我们的结算按档位掷（金币区间 + 一件按稀有度权重抽的遗物），差得远。所以加三条"这一场的奖励
修正"（与 §287 的欠账同一套：事件效果写、`roll_reward` 读一次就清）：

    fight_gold_set:<n>            这一场的金币**就是** n（不是加法）
    fight_relic_rarity:<rarity>   这一场那件遗物的稀有度**锁定**
    fight_extra_relic:<rarity>    这一场**再**给一件该稀有度的遗物（黑星的同一条路）

## ③ 楼层门槛

`Dead Adventurer` 只在第 7 层之后出现（wiki）。事件池的条目多一格 `MinFloor`：

    EventTables.Events: [{Id: "dead_adventurer", MinFloor: 7}, ...]

`Content::event_pool_at(pool, floor)` 过滤后再交给"掷一个"。**先筛后掷**（不是掷了再重掷）：
重掷会让"池子里有几个"影响随机流的位置，而"筛完掷一个"只影响范围。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:90])
    return s.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── 词表
    s = patch(s, '''/// | `fight_no_relic` | the **next** fight pays no relic (that search already found one) |''',
'''/// | `fight_no_relic` | the **next** fight pays no relic (that search already found one) |
/// | `fight_gold_set:<n>` | the **next** fight pays exactly `n` gold (`The Colosseum`'s 100) |
/// | `fight_relic_rarity:<rarity>` | the **next** fight's relic is locked to that rarity |
/// | `fight_extra_relic:<rarity>` | the **next** fight pays a **second** relic of that rarity |''')

    s = patch(s, '''            "fight_no_relic" => (Self::FightNoRelic, None),''',
'''            "fight_no_relic" => (Self::FightNoRelic, None),
            // §288：`The Colosseum` 的 VICTORY 奖励是**定数**（100 金币 + 一稀有 + 一罕见）。
            "fight_gold_set" => (Self::FightGoldSet(amount), None),''')

    s = patch(s, '''    /// §287：**下一场战斗**不掉遗物（那一件已经在搜索里拿到过了）。
    FightNoRelic,''',
'''    /// §287：**下一场战斗**不掉遗物（那一件已经在搜索里拿到过了）。
    FightNoRelic,
    /// §288：**下一场战斗**的金币**就是** `n`（加法之外的另一种：`The Colosseum` 的 100 不是
    /// "区间再加"，它把区间整个换掉）。
    FightGoldSet(i32),
    /// §288：**下一场战斗**那件遗物的稀有度被锁定。
    FightRelicRarity(Rarity),
    /// §288：**下一场战斗**再给一件该稀有度的遗物（`black_star` 走的是同一条"直接进包"的路）。
    FightExtraRelic(Rarity),''')

    # 稀有度词：`fight_relic_rarity:rare` / `fight_extra_relic:uncommon`
    s = patch(s, '''                    "gold_random" => {''',
'''                    // §288：稀有度写在词里（`fight_relic_rarity:rare`）。
                    "fight_relic_rarity" | "fight_extra_relic" => {
                        let rarity = match payload {
                            "common" => Rarity::Common,
                            "uncommon" => Rarity::Uncommon,
                            "rare" => Rarity::Rare,
                            // 别的稀有度（`Event` / `Shop` / `Boss`）不是"掉落稀有度"，
                            // 让它当奖励等于凭空造一件抽不到的东西。
                            _ => return None,
                        };
                        if kind == "fight_relic_rarity" {
                            (Self::FightRelicRarity(rarity), None)
                        } else {
                            (Self::FightExtraRelic(rarity), None)
                        }
                    }
                    "gold_random" => {''')

    # ── 运行层字段
    s = patch(s, '''    /// §287：下一场战斗**不掉遗物**（那一件已经搜到过；消费后清）。
    fight_no_relic: bool,''',
'''    /// §287：下一场战斗**不掉遗物**（那一件已经搜到过；消费后清）。
    fight_no_relic: bool,
    /// §288：下一场战斗的金币**定数**（`0` = 不覆盖）。
    fight_gold_set: i16,
    /// §288：下一场战斗那件遗物的**锁定稀有度**（`0` = 按权重抽；否则是 `Rarity` 的码 + 1）。
    fight_relic_rarity: u8,
    /// §288：下一场战斗**额外**给一件该稀有度的遗物（`0` = 没有）。
    fight_extra_relic: u8,
    /// §288：战斗之后要**回到的事件段**（空 = 战斗结算整个房间，§286 的老路）。
    event_resume: RunId,''')

    s = patch(s, '''            fight_no_relic: false,''','''            fight_no_relic: false,
            fight_gold_set: 0,
            fight_relic_rarity: 0,
            fight_extra_relic: 0,
            event_resume: RunId::EMPTY,''')

    # ── 应用
    s = patch(s, '''            EventEffect::FightNoRelic => {
                self.fight_no_relic = true;
            }''','''            EventEffect::FightNoRelic => {
                self.fight_no_relic = true;
            }
            EventEffect::FightGoldSet(n) => {
                self.fight_gold_set = i16::try_from(n).unwrap_or(i16::MAX);
            }
            EventEffect::FightRelicRarity(rarity) => {
                self.fight_relic_rarity = rarity_code(rarity);
            }
            EventEffect::FightExtraRelic(rarity) => {
                self.fight_extra_relic = rarity_code(rarity);
            }''')

    # ── EventMove：`After`
    s = patch(s, '''    /// §287：这一场战斗用哪个遭遇池（空 = 按档位用本幕标准池）。
    pub fight_pool: &'a str,
}''','''    /// §287：这一场战斗用哪个遭遇池（空 = 按档位用本幕标准池）。
    pub fight_pool: &'a str,
    /// §288：打赢之后**回到事件**的哪一段（空 = 战斗结算整个房间，§286 的老路）。
    pub fight_after: &'a str,
}''')
    s = patch(s, '''            fight: 0,
            fight_pool: "",
        }''','''            fight: 0,
            fight_pool: "",
            fight_after: "",
        }''')
    s = patch(s, '''            fight,
            fight_pool,
        } = event_move;''','''            fight,
            fight_pool,
            fight_after,
        } = event_move;''')

    # 战斗分支：`After` 存在时事件留着
    s = patch(s, '''            self.event = RunId::EMPTY;
            self.event_step = RunId::EMPTY;
            self.event_next = RunId::EMPTY;
            self.event_fight = fight;''',
'''            // §288：`After` 存在 ⇒ 事件**不收尾**（打完回来），只是暂时没有选项可点。
            if fight_after.is_empty() {
                self.event = RunId::EMPTY;
            }
            self.event_step = RunId::EMPTY;
            self.event_next = RunId::EMPTY;
            self.event_resume = if fight_after.is_empty() {
                RunId::EMPTY
            } else {
                RunId::new(fight_after).map_err(|_| RunError::NoSuchEvent)?
            };
            self.event_fight = fight;''')

    # ── 回到事件
    s = patch(s, '''    /// §278：事件**当前所在的那一段**（`EVND.Id`）。''',
'''    /// §288：战斗结束后**回到事件**（`The Colosseum`）。`false` = 这一场没有"回去"的地方
    /// （§286 的老路：战斗结算整个房间）。
    ///
    /// 调用方（`rd-wasm` 的 `apply_fight_outcome`）在**胜利**分支里问一次：
    /// `true` ⇒ **不发战斗奖励**（wiki 说那场战斗 "gives no rewards"，奖励就是事件继续），
    /// 事件重新摆到 `After` 那一段、`pending` 回到 `Event`。
    pub fn resume_event_after_fight(&mut self) -> bool {
        if self.event_resume.as_str().is_empty() {
            return false;
        }
        self.event_step = self.event_resume;
        self.event_resume = RunId::EMPTY;
        self.event_fight = 0;
        self.event_fight_pool = RunId::EMPTY;
        self.event_next = RunId::EMPTY;
        self.pending = Pending::Event;
        true
    }

    /// §278：事件**当前所在的那一段**（`EVND.Id`）。''')

    # ── 清点：`mark_resolved` / `begin_event`
    s = patch(s, '''        self.event_fight = 0;
        self.event_fight_pool = RunId::EMPTY;
        let node = self.node;''','''        self.event_fight = 0;
        self.event_fight_pool = RunId::EMPTY;
        self.event_resume = RunId::EMPTY;
        let node = self.node;''')

    s = patch(s, '''        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        self.event = id;''','''        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        self.fight_gold_set = 0;
        self.fight_relic_rarity = 0;
        self.fight_extra_relic = 0;
        self.event = id;''')

    # ── roll_reward：三条覆盖
    s = patch(s, '''        let bonus = i32::from(self.fight_gold_bonus);
        let no_relic = self.fight_no_relic;
        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        if bonus != 0 {
            paid = paid.saturating_add(bonus);
        }
        if no_relic {
            relic = RunId::EMPTY;
        }''',
'''        let bonus = i32::from(self.fight_gold_bonus);
        let no_relic = self.fight_no_relic;
        let gold_set = i32::from(self.fight_gold_set);
        let relic_rarity = self.fight_relic_rarity;
        let extra_rarity = self.fight_extra_relic;
        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        self.fight_gold_set = 0;
        self.fight_relic_rarity = 0;
        self.fight_extra_relic = 0;
        if gold_set > 0 {
            // §288：**定数**赢过区间（`The Colosseum` 的 100 不是"区间再加"）。
            paid = gold_set;
        }
        if bonus != 0 {
            paid = paid.saturating_add(bonus);
        }
        if no_relic {
            relic = RunId::EMPTY;
        }
        // §288：锁定稀有度（`The Colosseum` 的"1 Rare Relic"）。抽不到该稀有度就是**没有**
        // 遗物 —— 与"池子里没有可掉的"同一条路，而不是退回按权重抽。
        if relic_rarity != 0 {
            let wanted = rarity_of_code(relic_rarity);
            relic = self.pick_relic_of_rarity(RunStream::Reward, relic_pool, &[], wanted)?;
        }
        // §288：**第二件**遗物（"1 Uncommon Relic"）。直接进包，与 `black_star` 同一条路。
        if extra_rarity != 0 && !no_relic {
            let wanted = rarity_of_code(extra_rarity);
            let extra = self.pick_relic_of_rarity(RunStream::Reward, relic_pool, &[relic], wanted)?;
            if !extra.as_str().is_empty() {
                let _ = self.push_relic(extra.as_str(), card_pool);
            }
        }''')

    # ── 锁定稀有度的抽签：把候选扫描抽出来复用
    s = patch(s, '''    pub fn pick_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {''',
'''    /// §288：**指定稀有度**的遗物（`The Colosseum` 的 "1 Rare Relic"）。
    ///
    /// 与 [`Self::pick_relic`] 共用同一段候选扫描；差别只有一处：档位不掷，直接锁死。
    /// 该稀有度**抽不到**时返回空 id（"没有可给的"），与"池子空"同一个答案 ——
    /// 不退回按权重抽，否则"1 Rare Relic"会安静地变成"一件随便什么遗物"。
    pub fn pick_relic_of_rarity(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
        wanted: Rarity,
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner(stream, pool, reserved, Some(wanted))
    }

    pub fn pick_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner(stream, pool, reserved, None)
    }

    /// [`Self::pick_relic`] 的实体：`forced` = 锁定档位（`None` = 按权重掷）。
    fn pick_relic_inner(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
        forced: Option<Rarity>,
    ) -> Result<RunId, RunError> {''')

    s = patch(s, '''        let present = &rarities[..count];
        let band = self
            .pick_rarity(stream, &RELIC_RARITY_WEIGHTS, present)?
            .unwrap_or(pool[candidates[0]].rarity);''',
'''        let present = &rarities[..count];
        let band = match forced {
            Some(wanted) => wanted,
            None => self
                .pick_rarity(stream, &RELIC_RARITY_WEIGHTS, present)?
                .unwrap_or(pool[candidates[0]].rarity),
        };''')

    # 档位锁定但池子里没有该档 ⇒ 空 id（不是"退回第一件"）
    s = patch(s, '''        let chosen = if band_count == 0 {
            candidates[0]
        } else {''','''        let chosen = if band_count == 0 {
            if forced.is_some() {
                // §288：锁定的档位抽不到 ⇒ **没有**，不退回别的档位。
                return Ok(RunId::EMPTY);
            }
            candidates[0]
        } else {''')

    # ── 稀有度码：两个小函数（存盘只存一个字节）
    s = patch(s, '''/// The most nodes one step can offer''',
'''/// §288：`Rarity` 存进运行层的**一个字节**（`0` 留给"没锁定"）。
///
/// 为什么不存枚举：`RunState` 是 `Copy` 且逐字段进存档/回放，一个 `u8` 的编码比枚举的
/// 内存布局稳定得多；而"哪个数对应哪档"只有这两个函数知道。
#[must_use]
pub const fn rarity_code(rarity: Rarity) -> u8 {
    match rarity {
        Rarity::Basic => 1,
        Rarity::Common => 2,
        Rarity::Uncommon => 3,
        Rarity::Rare => 4,
        Rarity::Special => 5,
        Rarity::Curse => 6,
        Rarity::Status => 7,
    }
}

/// [`rarity_code`] 的逆。`0`（没锁定）与不认识的值都回 `Common` —— 调用方只在 `!= 0` 时用它。
#[must_use]
pub const fn rarity_of_code(code: u8) -> Rarity {
    match code {
        1 => Rarity::Basic,
        3 => Rarity::Uncommon,
        4 => Rarity::Rare,
        5 => Rarity::Special,
        6 => Rarity::Curse,
        7 => Rarity::Status,
        _ => Rarity::Common,
    }
}

/// The most nodes one step can offer''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-run: After / reward overrides / floor-ready')

    # ── rd-core：`After` 读进选项
    c = io.open(CORE, encoding='utf-8').read()
    c = patch(c, '''    /// §287：这一场战斗用哪个**遭遇池**（`Encounter`；空 = 按档位用本幕的标准池）。
    pub fight_pool: &'a str,''',
'''    /// §287：这一场战斗用哪个**遭遇池**（`Encounter`；空 = 按档位用本幕的标准池）。
    pub fight_pool: &'a str,
    /// §288：打赢之后**回到事件**的哪一段（`After`；空 = 战斗结算整个房间）。
    pub fight_after: &'a str,''')
    c = patch(c, '''                fight_pool: node.str_field("Encounter").ok().flatten().unwrap_or(""),''',
'''                fight_pool: node.str_field("Encounter").ok().flatten().unwrap_or(""),
                fight_after: node.str_field("After").ok().flatten().unwrap_or(""),''')
    c = patch(c, '''            fight_pool: "",
            fight: 0,''','''            fight_pool: "",
            fight_after: "",
            fight: 0,''')

    # ── rd-core：事件池按楼层筛
    c = patch(c, '''    /// The `?`-room event ids of one act (`port-plan.md` §133).''',
'''    /// §288：事件池**按楼层筛过**的 ids（`EventTables.<pool>` 的条目可以带 `MinFloor`）。
    ///
    /// `Dead Adventurer` 只在第 7 层之后出现（wiki）。**先筛后掷**：调用方拿到的列表就是
    /// 可掷的范围，于是"池子里有几个"不改变"筛掉几个"之后的随机流位置 —— 若改成
    /// "掷了发现不合格再重掷"，随机数会被它看不见的规则吃掉。
    #[must_use]
    pub fn event_pool_at(&self, pool: &str, floor: i32) -> Option<[&'a str; MAX_POOL_IDS]> {
        let hop = match pool {
            "Events" => "EventTables.Events",
            "Events2" => "EventTables.Events2",
            "Events3" => "EventTables.Events3",
            _ => return None,
        };
        let root = self.root_by_name("EventTables")?;
        let list = self.named_list_at(root, pool, hop)?;
        let mut out = [""; MAX_POOL_IDS];
        let mut count = 0usize;
        for term in list.iter() {
            let node = crate::ir::NodeRef::new(self, *term);
            let Some(id) = node.str_field("Id").ok().flatten().filter(|id| !id.is_empty()) else {
                continue;
            };
            // `MinFloor` 缺席 = 任何楼层都行（绝大多数事件）。
            let min_floor = node.int_field("MinFloor").ok().flatten().unwrap_or(0);
            if floor < min_floor {
                continue;
            }
            if count == MAX_POOL_IDS {
                // 池子比读得下的还长 ⇒ 拒绝，不截断（与 `id_pool` 同一条纪律）。
                return None;
            }
            out[count] = id;
            count += 1;
        }
        Some(out)
    }

    /// The `?`-room event ids of one act (`port-plan.md` §133).''')

    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('rd-core: After + event_pool_at')


main()
