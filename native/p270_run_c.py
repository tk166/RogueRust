"""§270 第三批：穷尽 match（两种形状）+ `reward_card_count` 走通用第二半表 + `holds_relic`。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

NEW_ARMS = [
    'RelicEffect::Omamori(_)',
    'RelicEffect::CurseMaxHealthUp(_)',
    'RelicEffect::CardAddGold(_)',
    'RelicEffect::UpgradeAddedCard(_)',
    'RelicEffect::GoldGainHeal(_)',
    'RelicEffect::NoGoldGain',
    'RelicEffect::FloorClimbGold(_)',
    'RelicEffect::RemovePriceFlat(_)',
    'RelicEffect::ShopDiscountPercent(_)',
]


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def insert_arms(src):
    """两种形状：`| X,`（链）与 `| X => {}`（`push_relic` 的"其余都不做事"组）。

    `push_relic` 那一组**排除** `Omamori`：它在那个 match 里有自己的臂（给 2 次），重复会变成
    unreachable pattern。
    """
    lines = src.split('\n')
    out = []
    chained = 0
    inline = 0
    for line in lines:
        stripped = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        if stripped == '| RelicEffect::RestCardReward,':
            for arm in NEW_ARMS:
                out.append(indent + '| ' + arm)
            chained += 1
        elif stripped == '| RelicEffect::RestCardReward => {}':
            for arm in NEW_ARMS:
                if arm.startswith('RelicEffect::Omamori'):
                    continue
                out.append(indent + '| ' + arm)
            inline += 1
        out.append(line)
    return '\n'.join(out), chained, inline


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① `reward_card_count` 改用第二半表
    old_count = '''        // §269：一件遗物有**两半**时（`busted_crown` = 每回合 +1 能量 **且** 奖励卡数 -2），
        // `relic_effect` 只能表达一个（它返回单个变体）。把第二半写在这张显式的小表里，
        // 比让 `relic_effect` 长出"返回多个"要小得多 —— 而"哪一半写在哪"在这里是**唯一的**。
        for (relic, delta) in EXTRA_REWARD_CARD_DELTAS.iter().copied() {
            if Self::relic_effect(relic).is_some() && {
                // 只问"有没有这件遗物"：表里的 id 是常量，`relic_effect` 一定认识它。
                let mut held = false;
                for slot in 0..self.relics_len as usize {
                    if self.relics[slot].as_str() == relic {
                        held = true;
                        break;
                    }
                }
                held
            } {
                count += delta;
            }
        }'''
    new_count = '''        // §270：一件遗物有**两半**时（`busted_crown` = 每回合 +1 能量 **且** 奖励卡数 -2），
        // `relic_effect` 只能表达一个（它返回单个变体）。第二半在 `RELIC_SECOND_HALVES` 里，
        // 这里只挑自己认识的那一类，其余忽略。
        for (relic, effect) in RELIC_SECOND_HALVES.iter().copied() {
            let RelicEffect::RewardCardDelta(delta, kinds) = effect else {
                continue;
            };
            if kinds.covers(kind) && self.holds_relic(relic) {
                count += delta;
            }
        }'''
    src = patch(src, old_count, new_count, 'reward_card_count second halves')

    # ② 穷尽 match
    src, chained, inline = insert_arms(src)
    assert (chained, inline) == (3, 1), 'sites: chained=%d inline=%d' % (chained, inline)
    print('exhaustive arms: chained %d, inline %d' % (chained, inline))

    # ③ `holds_relic`
    src = patch(src, '''    /// §270：这张牌进牌组时要不要换成 `+` 行（三个蛋）。''',
                '''    /// §270：身上有没有**这一件**遗物（按 id）。
    ///
    /// 与 `holds_relic_effect` 的区别：那个按**效果值**找（"有没有哪件遗物给我 +10 格挡"），
    /// 这个按**名字**找。`RELIC_SECOND_HALVES` 的消费者必需后者 —— 表里的第二半**不是**那件
    /// 遗物的 `relic_effect`，按值永远匹配不上。
    #[must_use]
    fn holds_relic(&self, id: &str) -> bool {
        for slot in 0..self.relics_len as usize {
            if self.relics[slot].as_str() == id {
                return true;
            }
        }
        false
    }

    /// §270：这张牌进牌组时要不要换成 `+` 行（三个蛋）。''', 'holds_relic')

    # ④ `combat_bonus_for` 消费第二半（`ectoplasm` 的能量载体）
    src = patch(src, '''        bonus
    }

    /// Take the `Burning Blood` heal''',
                '''        // §270：`RELIC_SECOND_HALVES` 里属于"开战加成"的那一类（`ectoplasm` 的每回合 +1 能量）。
        // 合并规则与上面那张表一致（同一条状态相加）—— 它产出的就是同一件事。
        for (relic, effect) in RELIC_SECOND_HALVES.iter().copied() {
            let RelicEffect::StartCombatStatus(id, stacks) = effect else {
                continue;
            };
            if !self.holds_relic(relic) {
                continue;
            }
            let mut merged = false;
            for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                if let Some(existing) = entry {
                    if existing.id == id {
                        existing.stacks += stacks;
                        merged = true;
                        break;
                    }
                }
            }
            if !merged {
                let _ = bonus.push_status(id, stacks);
            }
        }
        bonus
    }

    /// Take the `Burning Blood` heal''', 'combat_bonus second halves')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: matches + second halves consumers')


main()
