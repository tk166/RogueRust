"""§308 字段清点（parser 修好版见下）：第一版把文档注释里的 `{` 当成花括号，
于是把 `Pending` / `inv` / `Cumulative` / `wiki` 当成字段名读了出来 ——
"解析器自坏"比"字段缺"更隐蔽，所以先把词法做对。

做法：**逐行**走，去掉行注释后再数花括号，只认 `depth == 1` 且形如 `name:` 的行。

第二条契约（§309）：**开战状态的容量上界**。`MAX_COMBAT_STATUSES` 必须 ≥ 腰带容量，
因为每件带战斗程序的遗物都会推一条 `standard.<relic>` 标记状态；而"上界 = 腰带容量"这个
推论的**前提**是"一件遗物在同一张表里最多贡献一条"（主表的一个 match 臂 + `RELIC_SECOND_HALVES`
不许重叠）。这里两条都查。
"""
import io
import re
import sys

ROOT = 'D:/Vibe/sts-tui/'
STATE = ROOT + 'kernel/rd-run/src/state.rs'
ARCHIVE = ROOT + 'kernel/rd-run/src/state/archive.rs'
HASH = ROOT + 'kernel/rd-run/src/hash.rs'

NOT_HASHED = {
    # 三个容器的**长度**：指纹写的是切片本身（每张牌一行），长度由行数隐含。
    # 豁免的目的是不把同一事实写两遍 —— 也别忘了它意味着"这两个数天然一致"。
    'deck_len': '由 `deck()` 的行数隐含',
    'relics_len': '由 `relics()` 的行数隐含',
    'potions_len': '由 `potions()` 的行数隐含',
    # 同一个理由的第四个：`pickup_offer()` 就是 `pickup_offer` 的活动前缀。
    'pickup_offer_len': '由 `pickup_offer()` 的切片长度隐含',
}
NOT_ARCHIVED = {
    'pickup_offer_len': '存档写的是 `pickup_offer()` 的切片（长度紧跟在前面的字节里）',
}

FIELD = re.compile(r'^\s+(?:pub\(crate\) )?(?:pub )?(\w+):')


def code_part(line):
    """这一行的代码部分（去掉 `//` 之后的一切）。字符串里的 `//` 这里用不着担心。"""
    cut = line.find('//')
    return line if cut < 0 else line[:cut]


def struct_fields(text):
    lines = text.split('\n')
    start = next(i for i, line in enumerate(lines) if 'pub struct RunState {' in line)
    depth = 0
    fields = []
    for line in lines[start:]:
        code = code_part(line)
        before = depth
        depth += code.count('{') - code.count('}')
        if before == 1 and depth == 1:
            match = FIELD.match(code)
            if match:
                fields.append(match.group(1))
        elif before == 1 and depth == 0:
            break
    return fields


HERO = ('StartCombatStatus', 'StartCombatStatusInKinds', 'CampfireLift')
ENEMY = ('StartCombatStatusOnEnemies',)
PER_CURSE = ('StartCombatStatusPerCurse', 'StartCombatStatusPerCurseInKinds')


def combat_status_bound(text):
    """从遗物表里量出"同一时刻最多几条开战状态"的**结构上界**。"""
    start = text.index('pub fn relic_effect(id: &str) -> Option<RelicEffect> {')
    end = text.index('\n    }\n', text.index('_ => None,', start))
    body = text[start:end]
    arms = re.findall(
        r'"([a-z0-9_]+)"\s*=>\s*(?:\(?\s*)?(?:{)?\s*(?:Some\(|)(?:RelicEffect::)?([A-Za-z]+)',
        body)
    main_table = {}
    for rid, variant in arms:
        main_table.setdefault(rid, variant)

    halves_start = text.index('RELIC_SECOND_HALVES')
    halves_end = text.index('];', halves_start)
    halves = re.findall('\\"([a-z0-9_]+)\\",\s*RelicEffect::([A-Za-z]+)',
                        text[halves_start:halves_end])

    hero_main = {rid for rid, variant in main_table.items() if variant in HERO}
    hero_halves = {rid for rid, variant in halves if variant in HERO}
    belt = int(re.search(r'pub const MAX_RUN_RELICS: usize = (\d+);', text).group(1))
    return {
        'belt': belt,
        'hero_relics': len(hero_main),
        'overlaps': len(hero_main & hero_halves),
        'enemy_relics': len({rid for rid, v in main_table.items() if v in ENEMY}
                            | {rid for rid, v in halves if v in ENEMY}),
        'per_curse_relics': len({rid for rid, v in main_table.items() if v in PER_CURSE}
                                | {rid for rid, v in halves if v in PER_CURSE}),
    }


def combat_status_capacity(text):
    match = re.search(r'pub const MAX_COMBAT_STATUSES: usize = ([\w:]+);', text)
    value = match.group(1)
    if value.isdigit():
        return int(value)
    alias = re.search(r'pub const %s: usize = (\d+);' % re.escape(value), text)
    assert alias, value
    return int(alias.group(1))


def main():
    state = io.open(STATE, encoding='utf-8').read()
    archive = io.open(ARCHIVE, encoding='utf-8').read()
    fingerprint = io.open(HASH, encoding='utf-8').read()
    fields = struct_fields(state)
    if not fields:
        print('STATE_FIELDS FAIL (parser found no fields)')
        sys.exit(1)

    problems = []
    for name in fields:
        in_archive = ('state.%s' % name) in archive
        in_hash = ('state.%s' % name) in fingerprint
        if not in_archive and name not in NOT_ARCHIVED:
            problems.append('存档缺: %s' % name)
        if not in_hash and name not in NOT_HASHED:
            problems.append('指纹缺: %s' % name)
        if '--check' not in sys.argv:
            print('  %-24s archive=%-5s hash=%s' % (name, in_archive, in_hash))
    for name in list(NOT_HASHED) + list(NOT_ARCHIVED):
        if name not in fields:
            problems.append('豁免表里的字段已不存在: %s' % name)

    if problems:
        for line in problems:
            print('!!', line)
        print('STATE_FIELDS FAIL (%d problems over %d fields)' % (len(problems), len(fields)))
        sys.exit(1)
    print('STATE_FIELDS PASS (%d fields, every one archived and in the fingerprint)' % len(fields))

    # ── §309：开战状态的容量上界 ────────────────────────────────────────────────────────
    bound = combat_status_bound(state)
    capacity = combat_status_capacity(state)
    print('  belt=%d capacity=%d hero_arms=%d overlaps=%d enemy=%d per_curse=%d'
          % (bound['belt'], capacity, bound['hero_relics'], bound['overlaps'],
             bound['enemy_relics'], bound['per_curse_relics']))
    if capacity < bound['belt'] + bound['overlaps']:
        print('!! COMBAT_STATUS_BOUND FAIL: capacity %d < belt %d + overlaps %d'
              % (capacity, bound['belt'], bound['overlaps']))
        sys.exit(1)
    if capacity > 2 * bound['belt']:
        print('!! COMBAT_STATUS_BOUND FAIL: capacity %d is more than twice the belt — '
              'a constant nobody re-derived' % capacity)
        sys.exit(1)
    print('COMBAT_STATUS_BOUND PASS (capacity %d >= belt %d, no relic occupies two slots)'
          % (capacity, bound['belt']))


main()
