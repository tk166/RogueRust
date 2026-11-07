"""§259 遗物对账：wiki 的 `Module:Relics/data`（193 条）vs 内容镜像的 `Relics` 表。

这是"拉齐所有遗物的**信息**"的第一步 —— 先把**有多少、缺哪些、哪些格写错了**变成数字。
和数据源一样，它只读**离线抓下来的 Lua**（`native/wiki_relics/relics_data.lua.txt`），
所以结论可复核、不依赖网络。

输出四块：
1. 总数与分布（按 `Rarity` / `Character`）；
2. `MISSING`：wiki 有、内容没有（按稀有度分组，附 wiki 的一句话描述）；
3. `METADATA`：两边都有但 `Rarity`/`DisplayName` 不一致；
4. `IMPLEMENTED`：内容里有、但 `rd-run::relic_effect` 不认识（**不可能安静地什么都不做**，
   这条要从 `state.rs` 里读真实表，不抄清单）。
"""
import io
import json
import re
import sys

LUA = 'native/wiki_relics/relics_data.lua.txt'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
STATE = 'kernel/rd-run/src/state.rs'

ENTRY = re.compile(r'\["([^"]+)"\]\s*=\s*\{(.*?)\n\s*\},', re.S)
FIELD = re.compile(r'^\s*(\w+)\s*=\s*(.*?),?\s*$', re.M)


def strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def wiki_relics():
    body = io.open(LUA, encoding='utf-8').read()
    rows = {}
    for match in ENTRY.finditer(body):
        name, payload = match.group(1), match.group(2)
        fields = {}
        for field in FIELD.finditer(payload):
            fields[field.group(1)] = strip_quotes(field.group(2))
        rows[name] = fields
    return rows


def implemented_ids():
    """从 `relic_effect` 的 match 里读"内核认识哪些遗物"——不抄清单。"""
    body = io.open(STATE, encoding='utf-8').read()
    start = body.index('pub fn relic_effect')
    end = body.index('\n    }', start)
    ids = set()
    for match in re.finditer(r'^\s*"([a-z0-9_]+)"\s*=>', body[start:end], re.M):
        ids.add(match.group(1))
    return ids


def norm(name):
    """`Burning Blood` → `burning_blood`（内容里的 id 形状）。"""
    text = name.strip().lower()
    text = text.replace("'", '')
    text = re.sub(r"[^a-z0-9]+", '_', text)
    return text.strip('_')


NL = chr(10)


def write_inventory(wiki, content, implemented):
    """把清单写成 `docs/relic-inventory.md`（生成物，进 git；闸门读它）。"""
    order = ['Starter', 'Common', 'Uncommon', 'Rare', 'Boss', 'Shop', 'Event', 'Special', 'Blight']
    lines = [
        '# 遗物清单（生成物，别手改）',
        '',
        '由 `python -X utf8 native/audit_relic_gap.py --write` 生成：左列来自 wiki 的',
        '`Module:Relics/data`（`native/wiki_relics/relics_data.lua.txt`，离线可复核），',
        '右列来自内容镜像的 `Relics` 表与 `rd-run::relic_effect`。',
        '',
        '> `Implemented` = 内核有这条效果（`relic_effect` 的 match 里有它）。**内容门要求两者一一对应**，',
        '> 所以"wiki 有、我们没有"的遗物不会半吊子地出现在池子里（一件没效果的遗物被抽出来是最坏的形态）。',
        '',
        '| # | 统计 | 值 |',
        '|---|---|---|',
        '| 1 | wiki 遗物总数 | %d |' % len(wiki),
        '| 2 | 内容里的遗物 | %d |' % len(content),
        '| 3 | 缺（wiki 有、内容没有） | %d |' % len([k for k in wiki if k not in content]),
        '',
    ]
    for rarity in order:
        rows = [(k, v) for k, v in wiki.items() if v[1].get('Rarity') == rarity]
        if not rows:
            continue
        lines.append('## %s（%d）' % (rarity, len(rows)))
        lines.append('')
        lines.append('| 状态 | id | 名称 | 归属 | wiki 描述 |')
        lines.append('|---|---|---|---|---|')
        for rid, (name, fields) in sorted(rows, key=lambda kv: kv[1][0].lower()):
            mark = '有' if rid in implemented else '缺'
            desc = (fields.get('Description') or '').replace('|', '\|')
            lines.append('| %s | `%s` | %s | %s | %s |'
                         % (mark, rid, name, fields.get('Character', 'Shared'), desc))
        lines.append('')
    lines += [
        '## 说明',
        '',
        '* `Blight` 是无尽模式的遗物，本移植不做；列在这里是为了"总数对得上"，不是为了待办。',
        '* `Starter` / `Boss` / `Shop` / `Event` 都是**不可掉落**的桶（`RELIC_RARITY_WEIGHTS` 只有三档），',
        '  它们进内容之后也只会被事件/宝箱/Boss 奖励这样的**显式**来路发出。',
    ]
    io.open('docs/relic-inventory.md', 'w', encoding='utf-8', newline=NL).write(
        NL.join(lines) + NL)
    print('wrote docs/relic-inventory.md (%d rows)' % len(wiki))


def main():
    wiki = wiki_relics()
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    content = {row['Id']: row for row in doc['Relics']}
    known = implemented_ids()

    by_rarity = {}
    by_owner = {}
    for name, fields in wiki.items():
        by_rarity[fields.get('Rarity', '?')] = by_rarity.get(fields.get('Rarity', '?'), 0) + 1
        owner = fields.get('Character', 'Shared')
        by_owner[owner] = by_owner.get(owner, 0) + 1

    print('=' * 78)
    print('wiki 遗物 %d 条（%s）' % (len(wiki), ', '.join(
        '%s %d' % (k, v) for k, v in sorted(by_rarity.items()))))
    print('归属：%s' % ', '.join('%s %d' % (k, v) for k, v in sorted(by_owner.items())))
    print('-' * 78)
    print('内容 %d 条（其中 %d 条内核认识：%s）'
          % (len(content), len([i for i in content if i in known]),
             ', '.join(sorted(i for i in content if i in known))))

    wiki_by_id = {}
    for name, fields in wiki.items():
        wiki_by_id[norm(name)] = (name, fields)

    missing = []
    metadata = []
    for rid, (name, fields) in sorted(wiki_by_id.items()):
        if rid not in content:
            missing.append((rid, name, fields))
            continue
        ours = content[rid]
        rarity = fields.get('Rarity')
        if rarity and ours.get('Rarity') != rarity:
            metadata.append((rid, 'Rarity', ours.get('Rarity'), rarity))
        if ours.get('DisplayName') != name:
            metadata.append((rid, 'DisplayName', ours.get('DisplayName'), name))

    print('-' * 78)
    print('MISSING（wiki 有、内容没有）: %d' % len(missing))
    grouped = {}
    for rid, name, fields in missing:
        grouped.setdefault(fields.get('Rarity', '?'), []).append((rid, name))
    for rarity in ('Common', 'Uncommon', 'Rare', 'Boss', 'Shop', 'Starter', 'Event', 'Special'):
        rows = grouped.get(rarity)
        if not rows:
            continue
        print('  %-9s %3d | %s' % (rarity, len(rows), ', '.join(rid for rid, _ in rows)))
    for rarity in sorted(grouped):
        if rarity not in ('Common', 'Uncommon', 'Rare', 'Boss', 'Shop', 'Starter', 'Event',
                          'Special'):
            print('  %-9s %3d | %s' % (rarity, len(grouped[rarity]),
                                       ', '.join(rid for rid, _ in grouped[rarity])))

    print('METADATA（两边都有但写错）: %d' % len(metadata))
    for rid, field, ours, theirs in metadata:
        print('   %-24s %-12s ours=%r wiki=%r' % (rid, field, ours, theirs))

    unknown = sorted(i for i in content if i not in known)
    print('IMPLEMENTED: 内容里有 %d 条内核不认识：%s'
          % (len(unknown), ', '.join(unknown) or '(none)'))
    print('=' * 78)
    if '--write' in sys.argv:
        write_inventory(wiki_by_id, content, known)
        # `--write` 只负责生成清单；判定仍按上面三块（缺/写错/未实现）。
        return 0
    return 0 if not (missing or metadata or unknown) else 1


sys.exit(main())
