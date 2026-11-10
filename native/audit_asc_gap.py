"""§258 审计：**wiki 说了升档、内容没有变体** 的招式还有几条。

§190 把 `ProgramAsc` 从 13 条补到 42 条，之后没人再系统核过。这个脚本把两边逐条对上：

* 左：`native/wiki_asc/*.txt`（wikitext 原样，`{{Asc|N|…}}` 是升档的唯一可信来源）；
* 右：内容镜像里每条 `EACT` 的 `ProgramAsc` 阈值。

三种输出，第三种最值钱：

1. `MISSING`  —— wiki 有升档、内容没有 ⇒ 要补；
2. `MISMATCH` —— 阈值对不上（§257 抓到的 Nemesis/Reptomancer 的 4/19 就是这个形状）；
3. `EXTRA`    —— 内容有、wiki 没写 ⇒ 要么是我们自己发明的，要么 wiki 页面没写全，都得看。

用法：`python -X utf8 native/audit_asc_gap.py`
"""
import io
import json
import os
import re
import sys

DIR = 'native/wiki_asc'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

# ⚠️ §330：**不要**用 `\{\{Intents Table/row([\s\S]*?)\}\}` —— 非贪婪匹配会在第一个
# `{{Asc|2|4}}` 的 `}}` 处截断，于是每行只读到**第一个**升档。改成按"下一个 row / end"切块。
ROW_SPLIT = re.compile(r"\{\{Intents Table/(?:row|end)")
ASC = re.compile(r"\{\{Asc\|(\d+)\|")
BOX = re.compile(r"\{\{Enemy Infobox([\s\S]*?)\}\}")


def norm(text):
    """`Multi Stab` / `Multi-Stab` / `multi_stab` 都要能对上。"""
    text = text.strip().lower()
    text = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def wiki_rows():
    """(页面, 怪物显示名, 招式名, 升档阈值集合)。"""
    out = []
    for name in sorted(os.listdir(DIR)):
        if not name.endswith('.txt'):
            continue
        text = io.open(os.path.join(DIR, name), encoding='utf-8').read()
        boxes = [(m.start(), m.group(1)) for m in BOX.finditer(text)]
        # 每个 row 的 body = 从它自己的 `row` 标记到下一个 `row`/`end` 标记之间。
        marks = [m.start() for m in ROW_SPLIT.finditer(text)]
        for index, start in enumerate(marks):
            end = marks[index + 1] if index + 1 < len(marks) else len(text)
            body = text[start:end]
            match = re.match(r".*", body)  # 占位，保持下面的缩进形状
            move = re.search(r"\|\s*Name\s*=\s*([^|\n]+)", body)
            if not move:
                continue
            # 这一行属于**前面最近**的那个 infobox（同一个页面可能装三只怪）。
            box_name = '?'
            for box_start, box in boxes:
                if box_start > start:
                    break
                found = re.search(r"\|\s*Name\s*=\s*([^|\n]+)", box)
                if found:
                    box_name = found.group(1).strip()
            thresholds = sorted({int(t) for t in ASC.findall(body)})
            if thresholds:
                out.append((name[:-4], box_name, move.group(1).strip(), thresholds))
    return out


def content_index():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    monsters = {norm(row['NameKey']): row['Id'] for row in doc['Monsters'] if row.get('NameKey')}
    # 显示名里带括号的（`Spike Slime (L)`）在内容里叫 `spike_slime_s`/`_m`/`_l` 之类，所以
    # 名字对不上时退回"按语义前缀找" —— 但那样会误配，所以只报"整体对不上"，不猜。
    actions = {}
    for row in doc['EnemyActions']:
        prefix, _, move = row['Id'].partition('.')
        actions.setdefault((prefix, norm(move)), row)
    return doc, monsters, actions


def roll_levels(doc):
    """每个怪物在 `ENCT.Enemies[].Rolls` 里出现的升档等级（骰子范围的 A 档）。"""
    levels = {}
    for encounter in doc['Encounters']:
        for enemy in encounter['Enemies']:
            if 'Id' not in enemy:
                continue
            for roll in enemy.get('Rolls') or []:
                level = roll.get('AscensionMin') or 0
                if level:
                    levels.setdefault(enemy['Id'], set()).add(int(level))
    return levels


from asc_other_means import BY_OTHER_MEANS  # noqa: E402  (§330: 与闸门 `[7b]` 同一份)


def main():
    rows = wiki_rows()
    doc, monsters, actions = content_index()
    rolls = roll_levels(doc)
    missing, mismatch, extra, unresolved, via_rolls = [], [], [], [], []
    via_other = []

    for page, box, move, thresholds in rows:
        monster = monsters.get(norm(box))
        if monster is None:
            unresolved.append((page, box, move, thresholds))
            continue
        row = actions.get((monster, norm(move)))
        if row is None:
            unresolved.append((page, box + ' / ' + move, '', thresholds))
            continue
        have = [v['AscensionMin'] for v in (row.get('ProgramAsc') or [])]
        if row['Id'] in BY_OTHER_MEANS:
            via_other.append((row['Id'], thresholds, BY_OTHER_MEANS[row['Id']]))
            continue
        if not have:
            # §330：骰子范围（`Rolls`）是**另一条载体** —— 那一档已经表达了，不是缺口。
            if set(thresholds) <= rolls.get(monster, set()):
                via_rolls.append((row['Id'], thresholds))
                continue
            missing.append((row['Id'], thresholds))
        elif sorted(have) != thresholds:
            # 内容比 wiki 这一行**多**一档 ⇒ EXTRA（人看）；少一档 ⇒ MISMATCH（真缺口）。
            if set(thresholds) <= set(have):
                extra.append((row['Id'], thresholds, sorted(have)))
            else:
                mismatch.append((row['Id'], thresholds, sorted(have)))

    print('=' * 72)
    print('wiki 行（有升档）: %d' % len(rows))
    print('内容有变体的动作  : %d'
          % sum(1 for row in doc['EnemyActions'] if row.get('ProgramAsc')))
    print('-' * 72)
    print('MISSING  (wiki 有升档、我们没有): %d' % len(missing))
    for action_id, thresholds in missing:
        print('   %-34s wiki=%s' % (action_id, thresholds))
    if via_rolls:
        print('VIA_ROLLS (档位由 `ENCT.Enemies[].Rolls` 表达，不是缺口): %d' % len(via_rolls))
        for action_id, thresholds in via_rolls:
            print('   %-34s wiki=%s' % (action_id, thresholds))
    if via_other:
        print('VIA_OTHER_MEANS (档位由别的机制表达，见 native/asc_other_means.py): %d'
              % len(via_other))
        for action_id, thresholds, why in via_other:
            print('   %-34s wiki=%-8s %s' % (action_id, thresholds, why[:60]))
    if extra:
        print('EXTRA (内容有、wiki 这一行没写 —— 要么是我们发明的，要么 wiki 没写全): %d'
              % len(extra))
        for action_id, wiki, have in extra:
            print('   %-34s wiki=%s ours=%s' % (action_id, wiki, have))
    print('MISMATCH (阈值不一致): %d' % len(mismatch))
    for action_id, wiki, have in mismatch:
        print('   %-34s wiki=%s ours=%s' % (action_id, wiki, have))
    if unresolved:
        print('UNRESOLVED (名字对不上，需人看): %d' % len(unresolved))
        for page, box, move, thresholds in unresolved:
            print('   %-16s %-40s %s' % (page, box + ' / ' + move, thresholds))
    print('=' * 72)
    return 0 if not (missing or mismatch) else 1


sys.exit(main())
