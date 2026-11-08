"""§290 两个原子：`gold_all`（失去**全部**金币）与 `card:<id>`（给**指定**一张牌）。

## `gold_all`

wiki 的 `Masked Bandits` `[Pay]`："you lose **ALL** of your Gold"。它与 `gold_cost:<n>` 的区别
不是"数字大小"，而是**没有数字**：金额由局面决定（`self.gold`）。写成 `gold_cost:0` 是错的
（那什么都不扣），写成 `gold_cost:999` 也是错的（付不起 ⇒ 拒绝，而 wiki 的 `[Pay]` 永远付得起）。

⚠️ 顺序：`adjust_gold` 自己钳到 0，所以"扣掉现有金币"是 `adjust_gold(-self.gold)` —— 但
`ectoplasm` 会拦"获得金币"，不该拦"失去"。所以这里只走 `adjust_gold` 的**扣减**分支。

## `card:<id>`

`curse:<id>` 只能给诅咒（它**验**过池子里那一行是 `Rarity::Curse`）。有的奖励是**指定**的
普通/特殊卡 —— `The Nest` 的 `Ritual Dagger`（`Rarity::Special`）。所以：

    card:<card id>     载荷是内容里的卡 id，**任何**稀有度都行（含 Special）

`push_card` 负责所有"得到一张牌"的规则（`omamori` 挡诅咒、三个蛋升级、`ceramic_fish` 给钱），
所以这个原子**不写第二套** —— 它只是把池子里那一行递过去。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:90])
    return s.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── 词表文档
    s = patch(s, '''/// | `relic_random` | grant a **random** relic (Scrap Ooze).''',
'''/// | `card:<card id>` | grant **that** card (`The Nest`'s `Ritual Dagger`; any rarity) |
/// | `gold_all` | lose **all** gold (`Masked Bandits`'s `[Pay]`) -- no amount, the run decides |
/// | `relic_random` | grant a **random** relic (Scrap Ooze).''')

    # ── 枚举
    s = patch(s, '''    /// §285：**随机一件遗物**（`relic_random`）。''',
'''    /// §290：给**指定**的一张牌（`card:<id>`）。与 `GainCurse` 的区别只有一条：
    /// 它不要求 `Rarity::Curse`（`Ritual Dagger` 是 `Special`）。
    GainCard,
    /// §290：失去**全部**金币（`gold_all`）—— `Masked Bandits` 的 `[Pay]`。
    /// 没有金额：金额就是"现在有多少"。
    LoseAllGold,
    /// §285：**随机一件遗物**（`relic_random`）。''')

    # ── 解析：`card:<id>` 与裸词 `gold_all`
    s = patch(s, '''            "relic_random" => (Self::GainRandomRelic, None),''',
'''            "relic_random" => (Self::GainRandomRelic, None),
            // §290：`gold_all` 不带载荷（金额由局面决定）。
            "gold_all" => (Self::LoseAllGold, None),''')
    s = patch(s, '''                    "curse" => (Self::GainCurse, Some(payload)),''',
'''                    "curse" => (Self::GainCurse, Some(payload)),
                    // §290：`card:<id>` —— 与 `curse:` 同一个形状，只是不要求诅咒。
                    "card" => (Self::GainCard, Some(payload)),''')

    # ── 应用
    s = patch(s, '''            // §287：记在运行层，由 `roll_reward` 消费（一场战斗的账）。''',
'''            EventEffect::GainCard => {
                // 载荷必须是**这张镜像里真的存在**的卡：一个拼错的 id 会变成牌组里一张
                // 幽灵卡，直到某场战斗抽到它才暴露。稀有度**不限制**（`Ritual Dagger` 是 Special）。
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                let Some(row) = pool.iter().find(|card| card.id == id) else {
                    return Err(RunError::NoSuchCard);
                };
                self.push_card(*row)?;
            }
            EventEffect::LoseAllGold => {
                // §290：`[Pay]` —— 永远付得起（金额就是现有金币），所以这里**不会**报
                // `NotEnoughGold`。`adjust_gold` 走的是"失去"那一条，`ectoplasm`
                // （拦"获得金币"）不该在这里插手。
                let all = self.gold;
                self.adjust_gold(-all);
            }
            // §287：记在运行层，由 `roll_reward` 消费（一场战斗的账）。''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-run: gold_all / card:<id>')

    # ── wasm：效果码（页面这一侧没有可画的码，`card:` 的落点在牌组里）
    p = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
    w = io.open(p, encoding='utf-8').read()
    w = patch(w, '''        | EventEffect::FightRelic
        | EventEffect::GainCurse''','''        | EventEffect::FightRelic
        | EventEffect::GainCard
        | EventEffect::GainCurse''')
    w = patch(w, '''        | EventEffect::FightPotionChance(_) => -1,''','''        | EventEffect::FightPotionChance(_)
        // §290：`gold_all` 与 `card:<id>` 的落点是"金币清零 / 牌组加一张"，
        // 页面上没有一条"效果码"能画它们（`-1` 与 `relic_random` 同一条规矩）。
        | EventEffect::LoseAllGold
        | EventEffect::GainCard => -1,''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(w)
    print('wasm: codes')

    # ── rd-core：镜像词表
    c = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
    d = io.open(c, encoding='utf-8').read()
    d = patch(d, '''            "fight_gold_bonus",
        ];''','''            "fight_gold_bonus",
            // §290：失去**全部**金币（`Masked Bandits` 的 `[Pay]`）。
            "gold_all",
        ];''')
    d = patch(d, '''                || prefix(effect, "curse:")''','''                || prefix(effect, "curse:")
                // §290：给指定的一张牌（`The Nest` 的 `Ritual Dagger`）。
                || prefix(effect, "card:")''')
    io.open(c, 'w', encoding='utf-8', newline='\n').write(d)
    print('rd-core: vocabulary')


main()
