"""§393：状态也要有**中文说明**（悬浮窗里那一段）。

## 玩家报的

"战斗界面的状态悬浮窗没有文字说明"。

## 根因

`zh.ts` 的 `statuses` 条目只有 `name`（legacy 文件里其实有 `desc`，但生成器只搬了名字），
而悬浮面板读的是 `displayText("statuses", id)` ⇒ 空 ⇒ 面板上写"（这一条没有说明文本）"。

## 三层来源（与名字同一套，§388）

1. **legacy**：`sts/content/statuses.json` 里本来就有 `desc`（八条：五条轴 + thorns / ritual /
   metallicize）⇒ 直接搬；
2. **跨表复用**：`standard.X` 的 `X` 在 relics / cards / potions 里有中文 `text`
   ⇒ 用那一份（`orichalcum` → "如果你在回合结束时没有任何 格挡，获得 6 点 格挡。"）；
3. **人工译名表**：`STATUS_ZH` 的每一条升级成 `{name, text}`，补一句中文说明。

查不到的仍然是"没有说明文本" —— 但闸门 56 会**逐条**盯着（见 §393 的判据）。
"""

import io

PATH = 'native/build_zh_i18n.py'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. legacy：搬 desc ─────────────────────────────────────────────────────
OLD = '''    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}'''
NEW = '''    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}
    # §393：legacy 里**本来就有** `desc`（中文说明），生成器以前只搬了名字 ⇒ 悬浮窗没字。
    legacy_text = {item['id']: item.get('desc', '') for item in statuses}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = {'name': legacy[axis]}'''
NEW = '''    def legacy_entry(status_id):
        """legacy 的一条 → `{name, text}`（`desc` 缺就只给名字）。"""
        name = legacy[status_id]
        desc = legacy_text.get(status_id, '')
        return {'name': name, 'text': desc} if desc else {'name': name}

    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = legacy_entry(axis)'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''    for status_id, name in legacy.items():
        out['statuses'].setdefault(status_id, {'name': name})'''
NEW = '''    for status_id in legacy:
        out['statuses'].setdefault(status_id, legacy_entry(status_id))'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''        if '.' not in status_id:
            out['statuses'].setdefault('standard.' + status_id, {'name': name})'''
NEW = '''        if '.' not in status_id:
            out['statuses'].setdefault('standard.' + status_id, legacy_entry(status_id))'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 2. 跨表复用：名字 + 说明一起搬 ────────────────────────────────────────
OLD = '''        for table in ('relics', 'cards', 'potions', 'monsters'):
            entry = out[table].get(short)
            if entry and entry.get('name'):
                out['statuses'][status_id] = {'name': entry['name']}
                reused += 1
                break'''
NEW = '''        for table in ('relics', 'cards', 'potions', 'monsters'):
            entry = out[table].get(short)
            if entry and entry.get('name'):
                # §393：**说明也一起搬** —— 状态与它来源本来就是同一句话
                # （`orichalcum` 的"没有格挡就获得 6 格挡"就是那条遗物的原文）。
                merged = {'name': entry['name']}
                if entry.get('text'):
                    merged['text'] = entry['text']
                out['statuses'][status_id] = merged
                reused += 1
                break'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 3. 人工表：name → {name, text} ───────────────────────────────────────
OLD = '''    for status_id, name in STATUS_ZH.items():
        out['statuses'].setdefault(status_id, {'name': name})'''
NEW = '''    for status_id, row in STATUS_ZH.items():
        entry = {'name': row[0]}
        if row[1]:
            entry['text'] = row[1]
        out['statuses'].setdefault(status_id, entry)'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('生成器：状态三层都带说明')
