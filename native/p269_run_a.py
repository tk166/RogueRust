"""§269 rd-run：战斗类型层 + 奖励层的轻资产钩子。用 `write` 生成（FACTS §2）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

VARIANT_ANCHOR = "    StartCombatStatusPerCurse(&'static str, i32),"
VARIANT_ADD = """    StartCombatStatusPerCurse(&'static str, i32),
    /// §269：**只在某几类战斗里**开战挂状态（`sling_of_courage`：精英战 +2 力量、
    /// `slavers_collar`：Boss/精英战每回合 +1 能量）。
    ///
    /// 为什么不是"再开一张表"：这条规则的两个参数（哪类战斗 + 哪条状态）都属于**运行层**
    /// （`FightKind` 是它自己的枚举），内容不知道"精英"是什么。
    StartCombatStatusInKinds(&'static str, i32, KindMask),
    /// §269：**只在某几类战斗里**开战治疗（`pantograph`：Boss 战回 25）。
    ///
    /// 上限由战斗构建方钳（血量是战斗状态的事），所以这里只给"想回多少"。
    StartCombatHealInKinds(i32, KindMask),
    /// §269：战斗奖励的**卡牌张数**修正（`question_card` +1、`busted_crown` -2、
    /// `prayer_wheel` 普通战 +1）。
    RewardCardDelta(i32, KindMask),
    /// §269：**药水必掉**（`white_beast_statue`）。
    PotionAlwaysDrops,
    /// §269：精英战敌人血量百分比修正（`preserved_insect`：-25）。与升阶的
    /// `enemy_health_bonus_percent` 走**同一条通道**，所以两个修正自动叠加。
    EliteEnemyHealthPercent(i32),

    /// §269：精英多掉一件遗物（`black_star`）。
    ///
    /// ⚠️ 这件**直接塞进包**而不是进奖励屏：奖励屏只有一个遗物槽（`Reward::relic`），
    /// 加第二个槽要改 ABI 与页面。写在这里是为了让偏差**可查**，而不是让它悄悄消失。
    EliteExtraRelic,"""

MASK_ANCHOR = "/// The most cards a run's deck may hold. See the module docs: exceeding it is an error, never a"
MASK_ADD = """/// §269：一组"哪几类战斗"的位掩码（[`RelicEffect::StartCombatStatusInKinds`] 等使用）。
///
/// 用位而不是 `[bool; 3]`：遗物表里写成常量字面量（`NORMAL | ELITE`），读起来就是 wiki 那句话
/// （"精英与 Boss 战"）。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct KindMask(pub u8);

impl KindMask {
    pub const NORMAL: KindMask = KindMask(1);
    pub const ELITE: KindMask = KindMask(2);
    pub const BOSS: KindMask = KindMask(4);
    pub const ALL: KindMask = KindMask(7);

    /// 这张掩码是否覆盖 `kind`。
    #[must_use]
    pub const fn covers(self, kind: FightKind) -> bool {
        let bit = match kind {
            FightKind::Normal => 1,
            FightKind::Elite => 2,
            FightKind::Boss => 4,
        };
        self.0 & bit != 0
    }
}

/// The most cards a run's deck may hold. See the module docs: exceeding it is an error, never a"""


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(VARIANT_ANCHOR) == 1
    src = src.replace(VARIANT_ANCHOR, VARIANT_ADD)
    assert src.count(MASK_ANCHOR) == 1
    src = src.replace(MASK_ANCHOR, MASK_ADD)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: 5 new RelicEffect variants + KindMask')


main()
