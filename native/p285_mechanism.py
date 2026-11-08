"""§285 机制：事件的**概率分支**（选项带 `Chance` / `NextFail`）+ 区间金币。

## 为什么（三个 Act 1 事件 + The Joust 都要它）

wiki：

* `Scrap Ooze`："Lose 3 (5) HP. **25%** chance to find a Relic." 每次失败 +1 HP、+10% 概率，
  最多 9 次；
* `World of Goop`：`[Gather Gold]` 得 75 金币、掉 11 血；`[Leave It]` **掉 20-50（A15 35-75）
  金币**，且"不会超过你手上的金币"；
* `Wing Statue`：`[Destroy]` 得 **50-80 金币**（还要求牌组里有单次 ≥10 伤害的攻击牌 —— 见偏差）；
* `The Joust`（Act 2）：`[Bet on the Champ]` 付 50 金币、**70%** 赢 100；`[Bet on the Murderer]`
  付 50、**30%** 赢 250。

两件东西就够：**一个掷骰分支**（`Chance` + 失败去哪个段）与**一个区间金币原子**
（`gold_random:min:max`）。

## 为什么掷骰在 run 层

`RunState` 拥有事件随机流（`RunStream::Event`，`?` 房分流与事件选择都在用它）。
把掷骰放进 `resolve_event_effects`，与"选哪个事件"同一个流、同一份账 ——
wasm 侧只负责**读** `Chance`/`NextFail` 并传进来。

## 为什么不用"事件计数器"做升级

`Scrap Ooze` 的"每次失败 +1 HP、+10%"完全可以用**段链**表达（9 段），因为 wiki 就是一张
9 行的表。加一个"事件内计数器"是**新状态**（进指纹、进存档、还要一条"什么之后清零"的规则），
而段链不需要 —— 树本来就是干这个的（§278）。
"""
import io

P_RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
P_CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    # ---------------------------------------------------------------- rd-run：EventEffect
    s = io.open(P_RUN, encoding='utf-8').read()

    s = patch(s, '''/// | `gold_cost:<n>` | **pay** `n` gold; refused when short (the wiki's *Cleric*) |''',
'''/// | `gold_cost:<n>` | **pay** `n` gold; refused when short (the wiki's *Cleric*) |
/// | `gold_random:<min>:<max>` | gain `runif(min, max)` gold (the Goop's "lose 20-50 Gold") |''')

    s = patch(s, '''    /// §280：**付** `n` 金币（`gold_cost`）。不够就拒绝 —— 不是"扣到 0 为止"。
    GoldCost(i32),''',
'''    /// §280：**付** `n` 金币（`gold_cost`）。不够就拒绝 —— 不是"扣到 0 为止"。
    GoldCost(i32),
    /// §285：**区间金币**（`gold_random:<min>:<max>`）。负区间 = 扣钱，而
    /// `adjust_gold` 会把结果夹在 0（正好是 wiki 那句 "never more than the Gold you are
    /// carrying"），所以 `[Leave It]` 掉 20-50 金币不需要第二套规则。
    GoldRandom(i32, i32),''')

    # 解析：`gold_random:min:max`（payload 里两个冒号段）
    s = patch(s, '''                    "heal_pct" => match parse_permille(payload) {''',
'''                    // §285：`gold_random:20:50` —— 两端都是**整数金币**（区间不是百分比）。
                    "gold_random" => {
                        let mut parts = payload.split(':');
                        let (Some(low), Some(high), None) =
                            (parts.next(), parts.next(), parts.next())
                        else {
                            return None;
                        };
                        match (low.parse::<i32>(), high.parse::<i32>()) {
                            // 端点必须有序，且两端都不为 0（`0:0` 是一条什么都不做的效果，
                            // 而是"看起来在掷骰"的装饰 —— 那正是这一节要避免的形状）。
                            (Ok(low), Ok(high))
                                if low <= high && !(low == 0 && high == 0) =>
                            {
                                (Self::GoldRandom(low, high), None)
                            }
                            _ => return None,
                        }
                    }
                    "heal_pct" => match parse_permille(payload) {''')

    # 应用
    s = patch(s, '''            EventEffect::GoldCost(cost) => {''',
'''            EventEffect::GoldRandom(low, high) => {
                // §285：与战斗随机**同一个取模偏置形态**，但走运行层的流 —— 一局的
                // 金币掷骰不该消耗战斗的 `(seed, step)`。
                let span = i64::from(high) - i64::from(low) + 1;
                let roll = self
                    .rng
                    .roll(RunStream::Event, u32::try_from(span).unwrap_or(1))
                    .map_err(|_| RunError::Capacity)?;
                let delta = low.saturating_add(roll as i32);
                self.adjust_gold(delta);
            }
            EventEffect::GoldCost(cost) => {''')
    io.open(P_RUN, 'w', encoding='utf-8', newline='\n').write(s)

    # ---------------------------------------------------------------- rd-core：Chance / NextFail
    c = io.open(P_CORE, encoding='utf-8').read()
    c = patch(c, '''    /// §279/§280：这个选项在镜像里的 term —— 条件（`Requires` / `RequiresAsc`）由''',
'''    /// §285：**概率分支**。`Some((chance, fail_step))` = 这个选项要掷一次骰：
    /// `chance`% 成功（走 `next`），否则去 `fail_step`。`None` = 一定成功（绝大多数选项）。
    ///
    /// 为什么放在选项上而不是效果里：掷骰决定的是"**去哪一段**"，那是树的结构，不是效果。
    pub roll: Option<(u8, &'a str)>,
    /// §279/§280：这个选项在镜像里的 term —— 条件（`Requires` / `RequiresAsc`）由''')
    c = patch(c, '''                next: node.str_field("Next").ok().flatten().unwrap_or(""),''',
'''                next: node.str_field("Next").ok().flatten().unwrap_or(""),
                // §285：`Chance` 与 `NextFail` 必须**成对**出现（一条有概率却没有失败分支的
                // 选项是内容错误，交给内容门拦；这里只在两者都读得出来时才算"要掷骰"）。
                roll: match (
                    node.int_field("Chance").ok().flatten(),
                    node.str_field("NextFail").ok().flatten(),
                ) {
                    (Some(chance), Some(fail)) if (1..=100).contains(&chance) && !fail.is_empty() => {
                        Some((chance as u8, fail))
                    }
                    _ => None,
                },''')
    c = patch(c, '''            next: "",
            term: ABSENT16,''','''            next: "",
            roll: None,
            term: ABSENT16,''')
    io.open(P_CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('§285 mechanism: Chance/NextFail + gold_random')


main()
