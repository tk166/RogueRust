"""§287 任务②③：战后补偿 + "这次不睡"的精英池。

## ② 战后补偿（`Dead Adventurer`）

wiki（两个来源一致）：被伏击并打赢之后，"**还没搜到**的奖励"由这一场战斗补发；
伏击前已经拿到的那一件**从战斗奖励里去掉**（否则会重复），而 30 金币那一件
正是"这场精英能多掉 30 金币"的原因。

我们的奖励流程是 `roll_reward(kind)`，它按档位掷，不知道"这一局少发了什么"。
所以加**两个**运行层字段，由事件的**进入效果**写、由 `roll_reward` 消费：

    fight_gold_bonus:<n>   这一场战斗的金币 + n（随后清 0）
    fight_no_relic          这一场战斗不掉遗物（随后清 false）

单写点/单消费点：事件效果写，`roll_reward` 清零。事件循环开新事件时也清一次
（`begin_event`），因为"欠账"属于**一个**事件。

## ③ "这次不睡"（Lagavulin 在伏击里醒着）

wiki：`Dead Adventurer` 的 Lagavulin **不进入睡眠**，第一回合直接 Siphon Soul。

睡眠是遭遇的静态属性（`ENCT.Enemies[].StartingStatuses` 里那条 `standard.lagavulin_asleep`），
而"醒着"是**这一次**的属性。把遭遇改掉会连普通精英战一起改，所以这里给事件一个
"用哪个池"的入口：

    选项：{ Fight: "elite", Encounter: "EventElite" }

`Encounter` 是 `EncounterTables` 里的**池名**（闭集，内容门查）。不写 ⇒ 按档位用本幕的标准池。
`EventElite` 里放的是醒着的 Lagavulin 变体（`enc_lagavulin_awake`：没有睡眠状态、
`lagavulin_step` 初值 2 ⇒ 第一回合就是 Siphon Soul）。

池名要进 `RunState`（`event_fight_pool`），与 `event_fight` 同一个清点（`mark_resolved`）：
"要不要打 / 用哪个池 / 战后按哪档结算"三个答案必须出自同一份状态，否则存档/回放一半就漂。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:90])
    return s.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── ① 词表：两个新原子
    s = patch(s, '''/// | `relic_random` | grant a **random** relic (Scrap Ooze).''',
'''/// | `fight_gold_bonus` | the **next** fight pays `Amount` extra gold (`Dead Adventurer`'s 30) |
/// | `fight_no_relic` | the **next** fight pays no relic (that search already found one) |
/// | `relic_random` | grant a **random** relic (Scrap Ooze).''')

    s = patch(s, '''            "nothing" => (Self::Nothing, None),''',
'''            "nothing" => (Self::Nothing, None),
            // §287：**下一场战斗**的奖励修正（`Dead Adventurer` 的战后补偿）。
            // 为什么是"欠账"而不是当场给：wiki 说这些奖励由**那场战斗**补发。
            "fight_gold_bonus" => (Self::FightGoldBonus(amount), None),
            "fight_no_relic" => (Self::FightNoRelic, None),''')

    s = patch(s, '''    /// §285：**随机一件遗物**（`relic_random`）。''',
'''    /// §287：**下一场战斗**多付 `n` 金币（`Dead Adventurer` 的"30 金币还没搜到"）。
    FightGoldBonus(i32),
    /// §287：**下一场战斗**不掉遗物（那一件已经在搜索里拿到过了）。
    FightNoRelic,
    /// §285：**随机一件遗物**（`relic_random`）。''')

    # ── ② 两个字段 + 访问器
    s = patch(s, '''    event_fight: u8,''',
'''    event_fight: u8,
    /// §287：这一场战斗用哪个**遭遇池**（空 = 按档位用本幕的标准池）。
    event_fight_pool: RunId,
    /// §287：下一场战斗的金币加成（`Dead Adventurer` 的 30；由 `roll_reward` 消费后清 0）。
    fight_gold_bonus: i16,
    /// §287：下一场战斗**不掉遗物**（那一件已经搜到过；消费后清）。
    fight_no_relic: bool,''')

    s = patch(s, '''            event_fight: 0,''','''            event_fight: 0,
            event_fight_pool: RunId::EMPTY,
            fight_gold_bonus: 0,
            fight_no_relic: false,''')

    s = patch(s, '''    /// §278：事件**当前所在的那一段**（`EVND.Id`）。''',
'''    /// §287：事件引来的那一场战斗该用哪个**遭遇池**（空 = 按档位用本幕的标准池）。
    ///
    /// 存在的理由只有一个：`Dead Adventurer` 的 Lagavulin **不睡觉**，而"睡觉"写在遭遇里
    /// （`ENCT` 的 `StartingStatuses`）—— 改遭遇会连普通精英战一起改，所以改成"这一次用另一个池"。
    #[must_use]
    pub fn event_fight_pool(&self) -> &str {
        self.event_fight_pool.as_str()
    }

    /// §278：事件**当前所在的那一段**（`EVND.Id`）。''')

    # ── ③ mark_resolved：同一个清点
    s = patch(s, '''        self.event_fight = 0;
        let node = self.node;''','''        self.event_fight = 0;
        self.event_fight_pool = RunId::EMPTY;
        let node = self.node;''')

    # ── ④ begin_event：欠账属于一个事件
    s = patch(s, '''        self.event = id;
        self.event_step = entry;''','''        // §287：战斗奖励的"欠账"属于**一个**事件；开新事件就清掉（否则它会漏进下一场战斗）。
        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        self.event = id;
        self.event_step = entry;''')

    # ── ⑤ EventMove：池名
    s = patch(s, '''    pub fight: u8,
}''','''    pub fight: u8,
    /// §287：这一场战斗用哪个遭遇池（空 = 按档位用本幕标准池）。
    pub fight_pool: &'a str,
}''')
    s = patch(s, '''            entry: &[],
            fight: 0,
        }''','''            entry: &[],
            fight: 0,
            fight_pool: "",
        }''')
    s = patch(s, '''            branches,
            entry,
            fight,
        } = event_move;''','''            branches,
            entry,
            fight,
            fight_pool,
        } = event_move;''')
    s = patch(s, '''            self.event = RunId::EMPTY;
            self.event_step = RunId::EMPTY;
            self.event_next = RunId::EMPTY;
            self.event_fight = fight;''','''            self.event = RunId::EMPTY;
            self.event_step = RunId::EMPTY;
            self.event_next = RunId::EMPTY;
            self.event_fight = fight;
            self.event_fight_pool = if fight_pool.is_empty() {
                RunId::EMPTY
            } else {
                RunId::new(fight_pool).map_err(|_| RunError::NoSuchEvent)?
            };''')

    # ── ⑥ 两个新效果的实现
    s = patch(s, '''            EventEffect::GainRandomRelic => {''',
'''            // §287：记在运行层，由 `roll_reward` 消费（一场战斗的账）。
            EventEffect::FightGoldBonus(n) => {
                self.fight_gold_bonus = self.fight_gold_bonus.saturating_add(n as i16);
            }
            EventEffect::FightNoRelic => {
                self.fight_no_relic = true;
            }
            EventEffect::GainRandomRelic => {''')

    # ── ⑦ roll_reward：消费
    s = patch(s, '''        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            relic = self.pick_relic(RunStream::Reward, relic_pool)?;
        }''','''        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            relic = self.pick_relic(RunStream::Reward, relic_pool)?;
        }
        // §287：**这一场**战斗的奖励欠账（`Dead Adventurer`）：金币加成与"不掉遗物"。
        // 单消费点：读一次就清，所以它不可能漏进下一场战斗。
        let bonus = i32::from(self.fight_gold_bonus);
        let no_relic = self.fight_no_relic;
        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        if bonus != 0 {
            paid = paid.saturating_add(bonus);
        }
        if no_relic {
            relic = RunId::EMPTY;
        }
        self.reward = Reward {''')

    # 反例也要看得见：`relic` 在奖励结构里是"有没有"。
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-run: reward debt + fight pool')

    # ── ⑧ rd-core：选项的 `Encounter`（池名）
    c = io.open(CORE, encoding='utf-8').read()
    c = patch(c, '''    /// §286：**这个选项是一场战斗**。`0` = 不是，`1` = 普通怪，`2` = 精英。''',
'''    /// §287：这一场战斗用哪个**遭遇池**（`Encounter`；空 = 按档位用本幕的标准池）。
    pub fight_pool: &'a str,
    /// §286：**这个选项是一场战斗**。`0` = 不是，`1` = 普通怪，`2` = 精英。''')
    c = patch(c, '''                fight: match node.str_field("Fight").ok().flatten().unwrap_or("") {''',
'''                fight_pool: node.str_field("Encounter").ok().flatten().unwrap_or(""),
                fight: match node.str_field("Fight").ok().flatten().unwrap_or("") {''')
    c = patch(c, '''            fight: 0,
            term: ABSENT16,''','''            fight_pool: "",
            fight: 0,
            term: ABSENT16,''')
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('rd-core: Encounter field')


main()
