"""§289 三件收尾：`fight_relic:<id>`（特定遗物）、`MaxFloor`（事件池上界）、
`fight_potion_chance:<pct>`（这一场独立的药水概率）。

## ① `fight_relic:<id>`

`fight_relic_rarity` 只能锁"稀有度"，而有的奖励是**指名**的（`Masked Bandits` 的
`Red Mask`）。`fight_relic:<id>` 把"下一场战斗那件遗物"钉成具体 id：

* 抽不到（不在池里 / 已持有）⇒ **没有遗物**（不退回按权重抽，否则"就是这一件"会变成
  "随便一件"）；
* 与 `fight_extra_relic` 一起用时，额外那一件照旧按稀有度抽 —— 两件事互不覆盖。

## ② `MaxFloor`

`MinFloor` 已经在（`Dead Adventurer` 第 7 层之后）。上界同样是 wiki 的事实：
`The Colosseum` 只在**第二幕上半场**出现。层号是**本幕内**的行号（换幕归零，`0..=ROWS`），
所以"上半场"就是 `MaxFloor: 7`（15 行地图的前半）。

## ③ `fight_potion_chance:<pct>`

药水掉落平时用**移动的概率**（40% 起，掉了 -10、没掉 +10，`§157`）。事件里的战斗不是
那一幕"药水荒"节奏的一部分，所以这一场可以**独立**按 pct 掷：

* 掷骰照旧只掷一次（随机流位置不动，回放才稳定）；
* **不移动** `potion_chance` —— 这正是"独立"的含义：这一场既不欠也不还那一幕的账。
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
    s = patch(s, '''/// | `fight_extra_relic:<rarity>` | the **next** fight pays a **second** relic of that rarity |''',
'''/// | `fight_extra_relic:<rarity>` | the **next** fight pays a **second** relic of that rarity |
/// | `fight_relic:<relic id>` | the **next** fight pays **exactly** that relic |
/// | `fight_potion_chance:<pct>` | the **next** fight rolls its potion at `pct`, independent of the
///   act's moving chance (which it also leaves untouched) |''')

    s = patch(s, '''    /// §288：**下一场战斗**再给一件该稀有度的遗物（`black_star` 走的是同一条"直接进包"的路）。
    FightExtraRelic(Rarity),''',
'''    /// §288：**下一场战斗**再给一件该稀有度的遗物（`black_star` 走的是同一条"直接进包"的路）。
    FightExtraRelic(Rarity),
    /// §289：**下一场战斗**那件遗物**指名**（`fight_relic:<id>`）。`Masked Bandits` 的
    /// `Red Mask` 就是"就是这一件"，不是"随便一件稀有遗物"。
    FightRelic,
    /// §289：**下一场战斗**的药水概率**独立**于那一幕的移动概率（`fight_potion_chance:<pct>`）。
    FightPotionChance(u8),''')

    s = patch(s, '''                    "fight_relic_rarity" | "fight_extra_relic" => {''',
'''                    // §289：`fight_relic:<id>` —— 载荷是**遗物 id**（内容门查它在不在 `REL` 表里）。
                    "fight_relic" => (Self::FightRelic, Some(payload)),
                    // §289：`fight_potion_chance:<pct>` —— 0..=100 的整数。
                    "fight_potion_chance" => match payload.parse::<u8>() {
                        Ok(pct) if pct <= 100 => (Self::FightPotionChance(pct), None),
                        _ => return None,
                    },
                    "fight_relic_rarity" | "fight_extra_relic" => {''')

    # ── 运行层字段
    s = patch(s, '''    /// §288：战斗之后要**回到的事件段**（空 = 战斗结算整个房间，§286 的老路）。
    event_resume: RunId,''',
'''    /// §288：战斗之后要**回到的事件段**（空 = 战斗结算整个房间，§286 的老路）。
    event_resume: RunId,
    /// §289：下一场战斗那件遗物的**指名**（空 = 按稀有度/权重抽）。
    fight_relic: RunId,
    /// §289：下一场战斗的**独立药水概率**（`255` = 不覆盖，所以 0..=100 都能表达）。
    fight_potion_chance: u8,''')

    s = patch(s, '''            event_resume: RunId::EMPTY,''','''            event_resume: RunId::EMPTY,
            fight_relic: RunId::EMPTY,
            fight_potion_chance: NO_POTION_OVERRIDE,''')
    s = patch(s, '''        self.fight_extra_relic = 0;
        self.event = id;
        self.event_step = entry;''','''        self.fight_extra_relic = 0;
        self.fight_relic = RunId::EMPTY;
        self.fight_potion_chance = NO_POTION_OVERRIDE;
        self.event = id;
        self.event_step = entry;''')

    # ── 应用
    s = patch(s, '''            EventEffect::FightExtraRelic(rarity) => {
                self.fight_extra_relic = rarity_code(rarity);
            }''','''            EventEffect::FightExtraRelic(rarity) => {
                self.fight_extra_relic = rarity_code(rarity);
            }
            EventEffect::FightRelic => {
                // 载荷是**内容里的遗物 id**；`relic:` 那一条同样在这里校验它（`apply_event_effect`
                // 的 `GainRelic` 分支会查池子）。这里只把名字记下来，验在 `roll_reward` 里
                // —— 「不在池里 ⇒ 没有遗物」比"事件点不动"更接近 wiki（奖励是那场战斗发的）。
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                self.fight_relic = RunId::new(id).map_err(|_| RunError::BadId)?;
            }
            EventEffect::FightPotionChance(pct) => {
                self.fight_potion_chance = pct;
            }''')

    # ── roll_reward：指名遗物 + 独立药水概率
    s = patch(s, '''        let relic_rarity = self.fight_relic_rarity;
        let extra_rarity = self.fight_extra_relic;''',
'''        let relic_rarity = self.fight_relic_rarity;
        let extra_rarity = self.fight_extra_relic;
        let named_relic = self.fight_relic;
        let potion_override = self.fight_potion_chance;''')
    s = patch(s, '''        self.fight_relic_rarity = 0;
        self.fight_extra_relic = 0;
        if gold_set > 0 {''','''        self.fight_relic_rarity = 0;
        self.fight_extra_relic = 0;
        self.fight_relic = RunId::EMPTY;
        self.fight_potion_chance = NO_POTION_OVERRIDE;
        if gold_set > 0 {''')

    s = patch(s, '''        // §288：锁定稀有度（`The Colosseum` 的"1 Rare Relic"）。''',
'''        // §289：**指名**的遗物（`Masked Bandits` 的 `Red Mask`）。与稀有度那一条互斥：
        // 指名更具体，所以它先说话。抽不到（不在池里 / 已持有）⇒ **没有遗物**。
        if !named_relic.as_str().is_empty() {
            let wanted = named_relic.as_str();
            let available = relic_pool.iter().any(|entry| entry.id == wanted)
                && !self.relics().iter().any(|held| held.as_str() == wanted);
            relic = if available {
                RunId::new(wanted).map_err(|_| RunError::BadId)?
            } else {
                RunId::EMPTY
            };
        }
        // §288：锁定稀有度（`The Colosseum` 的"1 Rare Relic"）。''')
    s = patch(s, '''        if relic_rarity != 0 {''','''        if relic_rarity != 0 && named_relic.as_str().is_empty() {''')

    # 药水：独立概率不移动追踪值
    s = patch(s, '''        let chance = self.potion_chance.clamp(0, 100) as u32;''',
'''        // §289：这一场可以**独立**掷（事件里的战斗不属于那一幕的药水荒节奏）。
        let independent = potion_override != NO_POTION_OVERRIDE;
        let chance = if independent {
            u32::from(potion_override)
        } else {
            self.potion_chance.clamp(0, 100) as u32
        };''')
    s = patch(s, '''        self.potion_chance = if rolled {
            (self.potion_chance - POTION_DROP_STEP).max(0)
        } else {
            (self.potion_chance + POTION_DROP_STEP).min(100)
        };''','''        // §289：独立概率的那一场**不移动**追踪值 —— 这正是"独立"的意思：
        // 这一场既不欠也不还那一幕的账（`The Colosseum` 的第二场就是这种）。
        if !independent {
            self.potion_chance = if rolled {
                (self.potion_chance - POTION_DROP_STEP).max(0)
            } else {
                (self.potion_chance + POTION_DROP_STEP).min(100)
            };
        }''')

    # 常量：`255` = 不覆盖（0..=100 都能表达）
    s = patch(s, '''pub const POTION_DROP_START: i32 = 40;''',
'''/// §289：`fight_potion_chance` 的"没有覆盖"。`0..=100` 都是合法概率，所以哨兵必须在这一段之外
/// —— `255` 让"0%"（永远不掉）与"没设"两件事都说得清。
pub const NO_POTION_OVERRIDE: u8 = 255;

pub const POTION_DROP_START: i32 = 40;''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-run: fight_relic / fight_potion_chance')

    # ── rd-core：`MaxFloor`
    c = io.open(CORE, encoding='utf-8').read()
    c = patch(c, '''            let min_floor = node.int_field("MinFloor").ok().flatten().unwrap_or(0);''',
'''            let min_floor = node.int_field("MinFloor").ok().flatten().unwrap_or(0);
            // §289：上界（`The Colosseum` 只在第二幕上半场）。缺席 = 没有上界。
            let max_floor = node.int_field("MaxFloor").ok().flatten().unwrap_or(0);''')
    c = patch(c, '''            if id.is_empty() || floor < min_floor {''',
'''            if id.is_empty() || floor < min_floor || (max_floor != 0 && floor > max_floor) {''')
    c = patch(c, '''    /// §288：事件池**按楼层筛过**的 ids（`EventTables.<pool>` 的条目可以带 `MinFloor`）。''',
'''    /// §288/§289：事件池**按楼层筛过**的 ids（`EventTables.<pool>` 的条目可以带
    /// `MinFloor` / `MaxFloor`）。''')
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('rd-core: MaxFloor')


main()
