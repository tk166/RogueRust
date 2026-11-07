"""§271 第二批：`RunError::PotionGainBlocked` + 四处穷尽 match。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

NEW_ARMS = [
    'RelicEffect::ShopEntryHeal(_)',
    'RelicEffect::UnknownRoomGold(_)',
    'RelicEffect::RestEntryNextCombatEnergy(_, _)',
    'RelicEffect::NoPotionGain',
    'RelicEffect::PotionUseHeal(_)',
]


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def insert_arms(src):
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
                out.append(indent + '| ' + arm)
            inline += 1
        out.append(line)
    return '\n'.join(out), chained, inline


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① 新错误变体已在 `streams.rs` 里加过（见同批脚本），这里只做穷尽 match

    # ② 穷尽 match
    src, chained, inline = insert_arms(src)
    assert (chained, inline) == (3, 1), 'sites: chained=%d inline=%d' % (chained, inline)
    print('exhaustive arms: chained %d, inline %d' % (chained, inline))

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: error + arms')


main()
