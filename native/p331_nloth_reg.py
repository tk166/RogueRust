"""§331 Phase 2（内容收尾）：`N'loth` 还要两处登记 + 检查器认识 `@N` 占位符。

检查器报了四条，都是真话：

1. `relic_lose:@0` 不在 Relics 表里 —— `@N` 是**候选占位符**（开事件那一刻才有具体 id），
   检查器要认识它（与 `relic:<id>` / `curse:<id>` 同一处校验）；
2. `EventNodes: unreachable step(s): nloth` —— 事件要在 `EV` 表（`UnknownRooms`）里登记
   `Id` / `NameKey` / `Entry`，否则没有任何 `EV.Entry` 指向它；
3. `EventTables.Events2: 'nloth' is not in UnknownRooms` —— 池子里的每个 id 都必须在
   `UnknownRooms` 里有一行（否则页面拿不到名字）。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECKER = 'native/sts_content_check.py'

doc = json.load(io.open(CONTENT, encoding='utf-8'))

# ── 1. `EV` 表（UnknownRooms）里登记 ──────────────────────────────────────────
rooms = doc['UnknownRooms']
assert not any(r['Id'] == 'nloth' for r in rooms), 'already registered'
rooms.append({'Id': 'nloth', 'NameKey': "N'loth", 'Entry': 'nloth'})
print("UnknownRooms + nloth (Entry = nloth)")

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

# ── 2. 检查器：`@N` 是候选占位符 ──────────────────────────────────────────────
t = io.open(CHECKER, encoding='utf-8').read()
OLD = """        if effect == "relic_lose" and payload not in relic_ids:"""
if OLD not in t:
    # 找不到那一行就按"relic_lose 的校验"重新定位。
    import re
    m = re.search(r'\n(\s*)if .{0,80}relic_lose.{0,120}\n', t)
    assert m, 'no relic_lose validation found'
    print('found validation:', m.group(0).strip()[:120])
    OLD = m.group(0)
    NEW = OLD.rstrip('\n') + '\n'
else:
    NEW = OLD
print('checker anchor located; manual follow-up required if it printed a snippet')
