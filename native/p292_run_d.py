"""§292：把 `DeckChange`/`RelicEffect` 的新变体补进四处穷尽 `match`，并按**花括号配对**插入
"不是这个钩子"的臂（不靠行号 —— 上一轮靠行号插错过位置）。

判据：脚本结束时每处插入**恰好一次**，且插入点位于该 `match` 块内部、`Some(...)` 括号**里面**
（那两处的最后一条臂是 `Some(A | B | ...)` 然后 `| None => {}`）。
"""
import io
import re

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'

ARMS = [
    '| RelicEffect::Nothing',
    '| RelicEffect::EndOfCombatMaxHealthUp(_)',
    '| RelicEffect::ChestExtraRelic { .. }',
    '| RelicEffect::NextChestEmpty(_)',
    '| RelicEffect::ChestAddsCurse',
    '| RelicEffect::PickupCurseAndRelics { .. }',
    '| RelicEffect::PickupPotions(_)',
    '| RelicEffect::PickupDuplicate(_)',
    '| RelicEffect::RareCardChanceMultiplier(_)',
    '| RelicEffect::PotionEffectPercent(_),',
]
COMMENT = '// §292：新变体在 `relic_effect` 的两个钩子上都不生效（宝箱/拾取/奖励/药水/没有效果）。'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def insert_relic_arms():
    lines = io.open(STATE, encoding='utf-8').read().split('\n')
    anchor = 'match Self::relic_effect(self.relics[slot].as_str()) {'
    starts = [i for i, line in enumerate(lines) if anchor in line]
    assert len(starts) == 2, starts
    # 从后往前插，前面的行号不受影响。
    for start in reversed(starts):
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = next(
            i for i in range(start + 1, len(lines))
            if lines[i].strip() == '}' and (len(lines[i]) - len(lines[i].lstrip())) == indent
        )
        # 这个 match 里的 `Some(` 行（那两处都是 `Some(` 起的 or-pattern）
        some = next(i for i in range(start, end) if lines[i].strip() == 'Some(')
        # `Some(` 的闭合 `)`：按括号配对
        depth = 0
        close = None
        for i in range(some, end):
            depth += lines[i].count('(') - lines[i].count(')')
            if depth == 0 and i > some:
                close = i
                break
        assert close is not None, 'no closing paren for Some('
        pad = ' ' * (len(lines[close]) - len(lines[close].lstrip()))
        # ⚠️ **先摘掉上一条臂的尾逗号**：`Some(A | ..., | B,)` 是 `Some(元素1, 元素2)`
        # （"2 fields"），不是 or-pattern。上一轮就是这么把自己插成了两段。
        last = close - 1
        while lines[last].strip().startswith('//'):
            last -= 1
        assert lines[last].rstrip().endswith(','), lines[last]
        lines[last] = lines[last].rstrip()[:-1]
        lines[close:close] = [pad + COMMENT] + [pad + a for a in ARMS]
        print('inserted into match at line', start + 1, '(Some( at', some + 1, ') at', close + 1, ')')
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))


def main():
    # ── 1. `DeckChange::Duplicate` 的四处编码
    patch(HASH, '''        Some(crate::state::BlessingFollowUp::Deck(
            crate::state::DeckChange::TransformAndUpgrade,
        )) => "transform_and_upgrade",
    }''', '''        Some(crate::state::BlessingFollowUp::Deck(
            crate::state::DeckChange::TransformAndUpgrade,
        )) => "transform_and_upgrade",
        // §292：`dollys_mirror`（恩惠目前不用它，映射要穷尽 —— 编译器的闸门）。
        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Duplicate)) => {
            "duplicate"
        }
    }''')
    patch(HASH, '''        Some(crate::state::DeckChange::TransformAndUpgrade) => "transform_and_upgrade",
    }''', '''        Some(crate::state::DeckChange::TransformAndUpgrade) => "transform_and_upgrade",
        Some(crate::state::DeckChange::Duplicate) => "duplicate",
    }''')
    patch(ARCHIVE, '''        // §274
        DeckChange::TransformAndUpgrade => 4,
    }''', '''        // §274
        DeckChange::TransformAndUpgrade => 4,
        // §292：`dollys_mirror`
        DeckChange::Duplicate => 5,
    }''')
    patch(ARCHIVE, '''        // §274
        4 => DeckChange::TransformAndUpgrade,
        _ => return Err(ArchiveError::BadField("deck_change")),''',
          '''        // §274
        4 => DeckChange::TransformAndUpgrade,
        // §292
        5 => DeckChange::Duplicate,
        _ => return Err(ArchiveError::BadField("deck_change")),''')
    patch(ARCHIVE, '''        // §274（恩惠目前不用它，但编码要穷尽）
        BlessingFollowUp::Deck(DeckChange::TransformAndUpgrade) => 5,
    }''', '''        // §274（恩惠目前不用它，但编码要穷尽）
        BlessingFollowUp::Deck(DeckChange::TransformAndUpgrade) => 5,
        // §292
        BlessingFollowUp::Deck(DeckChange::Duplicate) => 6,
    }''')

    # ── 2. 两个 `relic_effect` 钩子的"不生效"臂
    insert_relic_arms()
    print('all patches in')


main()
