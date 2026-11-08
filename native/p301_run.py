"""§301 `neows_lament`：运行层计数 + "前 3 场敌人 1 血"。

## 为什么计数在运行层

"你的**前 3 场**战斗"是一个**跨战斗**的事实 —— 战斗里看不到"这是第几场"，只有运行层知道。
所以 `RunState` 多一个 `fights: u8`（开战时 +1），而"这一场要不要压血"由运行层回答
（`enemy_health_override`）。

## 为什么是"覆盖成绝对 1"而不是百分比

`enemy_health_percent` 那条通道是给 `A7/A8/A9`（"敌人更肉"）用的**乘法**；而 wiki 说的是
"enemies **will have 1 HP**" —— 绝对值，与它们原本多少血无关。混进百分比通道会变成
"1% 血"，那是另一条规则。

## 谁写血

`rd-wasm` 在装好战斗之后写（与 `set_combat_hero_health` 同一个位置）：
**当前血与最大血都设 1**。只写当前血的话，血条会显示 `1/45`，而且任何治疗/上限逻辑都会
把这场仗变回去 —— wiki 的承诺是"它们只有 1 点血"。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① 变体
    patch(STATE, '''    /// §293：`singing_bowl` —— 加牌时**可以**改拿 +`amount` 上限（wiki: *"you may raise your Max''',
                 '''    /// §301：`neows_lament` —— 前 `fights` 场战斗里敌人的血量被**覆盖**成 `health`。
    ///
    /// 绝对值而不是百分比：wiki 说的是 *"Enemies in your first 3 combats will have 1 HP"*，
    /// 与它们原本多少血无关。`enemy_health_percent` 那条通道是乘法（`A7/A8/A9`），混用会让
    /// "1 血"变成"1% 血"。
    EnemyHealthInFirstFights {
        /// 生效几场（wiki: 3）。
        fights: u8,
        /// 那些场次里敌人的血量（wiki: 1）。
        health: i32,
    },
    /// §293：`singing_bowl` —— 加牌时**可以**改拿 +`amount` 上限（wiki: *"you may raise your Max''')

    # ── ② 表项
    patch(STATE, '''            "mummified_hand" => {
                Some(RelicEffect::StartCombatStatus("standard.mummified_hand", 1))
            }''', '''            "mummified_hand" => {
                Some(RelicEffect::StartCombatStatus("standard.mummified_hand", 1))
            }
            // §301：`neows_lament` —— 运行层规则（没有内容状态：它不是战斗内的状态）。
            "neows_lament" => Some(RelicEffect::EnemyHealthInFirstFights {
                fights: NEOWS_LAMENT_FIGHTS,
                health: NEOWS_LAMENT_HEALTH,
            }),''')

    # ── ③ 常量
    patch(STATE, '''pub const TINY_HOUSE_GOLD: i32 = 50;''',
                 '''pub const TINY_HOUSE_GOLD: i32 = 50;
/// §301：`neows_lament` —— "Enemies in your first **3** combats will have **1** HP"。
pub const NEOWS_LAMENT_FIGHTS: u8 = 3;
pub const NEOWS_LAMENT_HEALTH: i32 = 1;''')

    # ── ④ 字段
    patch(STATE, '''    /// §293：这一次可以挑的那几张（`pickup_add > 0` 时有意义）。
    pickup_offer: [RunId; MAX_REWARD_CARDS],
    pickup_offer_len: u8,
}''', '''    /// §293：这一次可以挑的那几张（`pickup_add > 0` 时有意义）。
    pickup_offer: [RunId; MAX_REWARD_CARDS],
    pickup_offer_len: u8,
    /// §301：这一局**已经打过几场**（开战时 +1）。`neows_lament` 用它数"前 3 场"。
    ///
    /// 数的是**开始**过的战斗，不是赢过的：「前 3 场」里输掉的那一场也占一格 —— 否则
    /// 输了一场之后遗物会变成"再送你三场"。
    fights: u8,
}''')
    patch(STATE, '''            pickup_offer: [RunId::EMPTY; MAX_REWARD_CARDS],
            pickup_offer_len: 0,''', '''            pickup_offer: [RunId::EMPTY; MAX_REWARD_CARDS],
            pickup_offer_len: 0,
            fights: 0,''')

    # ── ⑤ 访问器 + 计数 + 覆盖值（挂在 `pickup_add` 那段之前）
    patch(STATE, '''    /// §293：欠着**几张牌**要加进牌组（`orrery` 的 5、`tiny_house` 的 1）。0 = 不欠。''',
                 '''    /// §301：这一局已经打过几场（开战时 +1）。
    #[must_use]
    pub const fn fights(&self) -> u8 {
        self.fights
    }

    /// §301：**一场战斗开始了** —— 记一次。由调用方在开战那一刻调（`rd-wasm` 的
    /// `fight_begin`），因为"开战"这件事只有它知道。
    pub fn note_fight_started(&mut self) {
        self.fights = self.fights.saturating_add(1);
    }

    /// §301：`neows_lament` —— 这一场敌人的血量要不要被**覆盖**成某个绝对值。
    ///
    /// `None` = 不覆盖（绝大多数战斗走这一支）。数的是**已经开始**的场次：开战时先
    /// `note_fight_started` 再问这里，所以第 1 场读到的是 1。
    #[must_use]
    pub fn enemy_health_override(&self) -> Option<i32> {
        let Some(RelicEffect::EnemyHealthInFirstFights { fights, health }) =
            self.first_relic_effect_of(RelicEffect::EnemyHealthInFirstFights {
                fights: NEOWS_LAMENT_FIGHTS,
                health: NEOWS_LAMENT_HEALTH,
            })
        else {
            return None;
        };
        if self.fights <= fights {
            Some(health)
        } else {
            None
        }
    }

    /// §293：欠着**几张牌**要加进牌组（`orrery` 的 5、`tiny_house` 的 1）。0 = 不欠。''')

    # ── ⑥ 三处"不是这个钩子"的清单
    for old, new in (
        ('''            | RelicEffect::PotionEffectPercent(_)
            | RelicEffect::RestCardReward => {}''',
         '''            | RelicEffect::PotionEffectPercent(_)
            // §301：`neows_lament` 在**开战那一刻**生效（由调用方问 `enemy_health_override`）。
            | RelicEffect::EnemyHealthInFirstFights { .. }
            | RelicEffect::RestCardReward => {}'''),
    ):
        patch(STATE, old, new)

    s = io.open(STATE, encoding='utf-8').read()
    lines = s.split('\n')
    targets = [i for i, line in enumerate(lines)
               if line.strip() == '| RelicEffect::SingingBowl(_),']
    assert len(targets) == 2, len(targets)
    for i in reversed(targets):
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = lines[i].rstrip()[:-1]
        lines[i + 1:i + 1] = [f'{indent}// §301：`neows_lament` 也不是这两个钩子上的事。',
                             f'{indent}| RelicEffect::EnemyHealthInFirstFights {{ .. }},']
    s = '\n'.join(lines)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)

    # ── ⑦ hash
    patch(HASH, '''    // §271：`ancient_tea_set` 欠着的那一场（进篝火之后、下一场战斗之前）。''',
                '''    // §301：已经打过几场 —— `neows_lament` 的"前 3 场"就靠这个数。
    writer
        .str("fights=")
        .u32(u32::from(state.fights()))
        .str("\\n");
    // §271：`ancient_tea_set` 欠着的那一场（进篝火之后、下一场战斗之前）。''')

    # ── ⑧ 存档（VERSION 8 → 9）
    patch(ARCHIVE, '''/// §293：7 → 8（`pickup_add` + `pickup_offer`）。''',
                   '''/// §301：8 → 9（`fights`）。
/// §293：7 → 8（`pickup_add` + `pickup_offer`）。''')
    patch(ARCHIVE, '''const VERSION: u8 = 8;''', '''const VERSION: u8 = 9;''')
    patch(ARCHIVE, '''    // §293：欠着几张牌 + 这一手是哪几张。''',
                   '''    // §301：已经打过几场（`neows_lament` 的计数）。
    writer.byte(state.fights())?;
    // §293：欠着几张牌 + 这一手是哪几张。''')
    patch(ARCHIVE, '''    // §293：欠着几张牌 + 这一手是哪几张。
    let pickup_add = reader.byte()?;''', '''    // §301
    let fights = reader.byte()?;
    // §293：欠着几张牌 + 这一手是哪几张。
    let pickup_add = reader.byte()?;''')
    patch(ARCHIVE, '''    restored.pickup_add = pickup_add;''', '''    restored.fights = fights;
    restored.pickup_add = pickup_add;''')
    print('rd-run wired')


main()
