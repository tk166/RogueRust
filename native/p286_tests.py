"""§286：把测试里的 `resolve_event_effects(效果, next, roll, &pool)` 迁到 `EventMove`。

四条形态：
    resolve_event_effects(&[...], None, None, &pool)
    resolve_event_effects(&[...], Some("x"), None, &pool)
    resolve_event_effects(&[], Some("probe.success"), Some(EventRoll{..}), &pool)
    resolve_event_effects(&[], None, None, &pool)      ← `&[]` 效果
"""
import io
import re

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

PAT = re.compile(
    r'resolve_event_effects\(\s*(?:'
    r'(?P<effects>&\[[^\[\]]*(?:\[[^\]]*\][^\[\]]*)*\])'
    r')\s*,\s*'
    r'(?P<next>None|Some\("[^"]*"\))\s*,\s*'
    r'(?P<roll>None|Some\(EventRoll\s*\{[^}]*\}\))\s*,\s*'
    r'(?P<pool>&pool)\s*\)', re.S)


def main():
    s = io.open(P, encoding='utf-8').read()
    count = 0
    out = []
    pos = 0
    for m in PAT.finditer(s):
        count += 1
        effects = m.group('effects')
        next_ = m.group('next')
        roll = m.group('roll')
        # 缩进：让整块照原样缩进即可（`EventMove` 结构体字面量跨行）
        move = '&EventMove { effects: %s, next: %s' % (effects, next_)
        if roll != 'None':
            chance = re.search(r'chance:\s*(\d+)', roll)
            fail_to = re.search(r'on_fail:\s*("[^"]*")', roll)
            success = re.search(r'on_success:\s*("[^"]*")', roll)
            assert chance and fail_to and success, roll
            c = int(chance.group(1))
            move += (', branches: &[(%du8, %s), (%du8, %s)]'
                     % (c, success.group(1), 100 - c, fail_to.group(1)))
        move += ', ..EventMove::none() }'
        out.append(s[pos:m.start()])
        out.append('resolve_event_effects(' + move + ', &pool)')
        pos = m.end()
    out.append(s[pos:])
    s = ''.join(out)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('migrated %d call sites' % count)


main()
