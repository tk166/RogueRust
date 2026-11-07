"""§269 rd-run 第三批（最终版）：奖励层 + 遗物行 + 穷尽 match。

穷尽 match 有四处，形状相似（都以 `| RelicEffect::RestCardReward,` 收尾或与它相邻），
所以**按行插入**比猜锚点稳：凡是那种行，前面统一塞上这一批的新变体。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

NEW_ARMS = [
    'RelicEffect::StartCombatStatusInKinds(_, _, _)',
    'RelicEffect::StartCombatHealInKinds(_, _)',
    'RelicEffect::RewardCardDelta(_, _)',
    'RelicEffect::PotionAlwaysDrops',
    'RelicEffect::EliteExtraRelic',
    'RelicEffect::EliteEnemyHealthPercent(_)',
]


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def insert_arms(src):
    """在每处 `| RelicEffect::RestCardReward,` 之前插入这一批的新变体。"""
    lines = src.split('\n')
    out = []
    inserted = 0
    for line in lines:
        if line.strip() == '| RelicEffect::RestCardReward,':
            indent = line[:len(line) - len(line.lstrip())]
            for arm in NEW_ARMS:
                out.append(indent + '| ' + arm)
            inserted += 1
        out.append(line)
    return '\n'.join(out), inserted


def main():
    src = io.open(P, encoding='utf-8').read()

    # ---- ① 遗物行：奖励层五件
    src = patch(src, "            // `black_blood`：战后回 12（wiki 的 \"Replaces Burning Blood\" 那一半见 §268.3）。",
                """            // §269：**奖励层**五件。
            //   `question_card`：卡牌奖励 +1 张（任何战斗）；
            //   `busted_crown`：卡牌奖励 -2 张（能量那一半走 `busted_crown_energy` 状态）；
            //   `prayer_wheel`：**普通怪**多 1 张；
            //   `white_beast_statue`：药水必掉；
            //   `black_star`：精英多掉一件遗物（直接塞进包，理由见变体的文档）。
            "question_card" => Some(RelicEffect::RewardCardDelta(1, KindMask::ALL)),
            "busted_crown" => Some(RelicEffect::RewardCardDelta(-2, KindMask::ALL)),
            "prayer_wheel" => Some(RelicEffect::RewardCardDelta(1, KindMask::NORMAL)),
            "white_beast_statue" => Some(RelicEffect::PotionAlwaysDrops),
            "black_star" => Some(RelicEffect::EliteExtraRelic),
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。""",
                'reward relics')

    # ---- ② 拾取钩子（`push_relic` 的那一处，锚点是它的注释）
    src = patch(src, """            | RelicEffect::StartCombatStatusPerCurse(_, _)
            // §224: 开战给敌人的状态也不是"拿到就生效"。""",
                """            | RelicEffect::StartCombatStatusPerCurse(_, _)
            // §269：六个新变体都不是"拿到就生效"（两个按战斗类型、三个在奖励结算时、
            // 一个改精英血量）。
            | RelicEffect::StartCombatStatusInKinds(_, _, _)
            | RelicEffect::StartCombatHealInKinds(_, _)
            | RelicEffect::RewardCardDelta(_, _)
            | RelicEffect::PotionAlwaysDrops
            | RelicEffect::EliteExtraRelic
            | RelicEffect::EliteEnemyHealthPercent(_)
            // §224: 开战给敌人的状态也不是"拿到就生效"。""",
                'pickup match')

    # ---- ③ 其余三处穷尽 match：按行插入
    src, inserted = insert_arms(src)
    print('exhaustive match sites patched:', inserted)
    assert inserted == 3, 'expected three `| RelicEffect::RestCardReward,` sites, got %d' % inserted

    # ---- ④ `roll_reward`：卡数可变
    src = patch(src, """        if eligible_len < MAX_REWARD_CARDS {
            return Err(RunError::PoolTooSmall {
                pool: eligible_len,
                need: MAX_REWARD_CARDS,
            });
        }
        let eligible = &eligible[..eligible_len];
        let (low, high) = kind.gold();""",
                """        // §269：奖励的**卡数**是可变的（`question_card` +1、`busted_crown` -2、
        // `prayer_wheel` 普通战 +1）。`MAX_REWARD_CARDS` 是**存储**上限，与"这一屏给几张"
        // 是两个数 —— 把两者混成一个，加一张牌就要动所有下标。
        let wanted = self.reward_card_count(kind);
        if eligible_len < wanted {
            return Err(RunError::PoolTooSmall {
                pool: eligible_len,
                need: wanted,
            });
        }
        let eligible = &eligible[..eligible_len];
        let (low, high) = kind.gold();""",
                'reward count')

    src = patch(src, """        for slot in 0..MAX_REWARD_CARDS {
            // One roll, banded -- see `reward_bands`.""",
                """        for slot in 0..wanted {
            // One roll, banded -- see `reward_bands`.""",
                'reward loop')

    src = patch(src, """        self.reward = Reward {
            gold: paid,
            cards,
            cards_len: MAX_REWARD_CARDS as u8,""",
                """        self.reward = Reward {
            gold: paid,
            cards,
            cards_len: wanted as u8,""",
                'cards_len')

    # ---- ⑤ 药水必掉
    src = patch(src, """        let chance = self.potion_chance.clamp(0, 100) as u32;
        let rolled = self.rng.roll(RunStream::Potion, 100)? < chance;""",
                """        let chance = self.potion_chance.clamp(0, 100) as u32;
        // §269：`white_beast_statue` —— "Potions always appear in combat rewards"。
        // 掷骰照旧（随机流的位置不动，回放才稳定），只把**结果** OR 成真。
        let always = self.holds_relic_effect(RelicEffect::PotionAlwaysDrops);
        let rolled = always || self.rng.roll(RunStream::Potion, 100)? < chance;""",
                'potion always')

    # ---- ⑥ 精英额外遗物
    src = patch(src, """        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            relic = self.pick_relic(RunStream::Reward, relic_pool)?;
        }""",
                """        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            relic = self.pick_relic(RunStream::Reward, relic_pool)?;
        }
        // §269：`black_star` —— "Elites now drop an additional relic when defeated"。
        // ⚠️ 第二件**直接进包**（奖励屏只有一个遗物槽）。这不是"更省事"，是**代价最小**：
        // 加第二个槽要改 `Reward` 结构、ABI 与页面三处。偏差写在这里，别让它悄悄消失。
        if matches!(kind, FightKind::Elite)
            && self.holds_relic_effect(RelicEffect::EliteExtraRelic)
        {
            let extra = self.pick_relic(RunStream::Reward, relic_pool)?;
            if extra.as_str() != "" {
                if let Ok(id) = RunId::new(extra.as_str()) {
                    let _ = self.push_relic(id.as_str());
                }
            }
        }""",
                'elite extra relic')

    # ---- ⑦ reward_card_count
    src = patch(src, "    /// §259：`Dream Catcher` —— 休息之后给**一次卡牌奖励**",
                """    /// §269：这一屏**给几张**卡牌奖励。
    ///
    /// 基数 3（`inv:§3.5`）加上所有遗物的 `RewardCardDelta`（掩码覆盖这一场才算），再钳到
    /// `1..=MAX_REWARD_CARDS`。**下限 1**：`busted_crown` 的 -2 不能把一屏变成 0 张
    /// （那就不是"少两张"，而是"没有奖励" —— 另一条规则）。
    #[must_use]
    pub fn reward_card_count(&self, kind: FightKind) -> usize {
        let mut count = MAX_REWARD_CARDS as i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::RewardCardDelta(delta, kinds)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                if kinds.covers(kind) {
                    count += delta;
                }
            }
        }
        count.clamp(1, MAX_REWARD_CARDS as i32) as usize
    }

    /// §259：`Dream Catcher` —— 休息之后给**一次卡牌奖励**""",
                'reward_card_count')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: reward layer wired')


main()
