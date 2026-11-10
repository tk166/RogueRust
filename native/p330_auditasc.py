"""§330 修 `native/audit_asc_gap.py`：它的行解析**截断在第一个 `{{Asc|…}}`**。

`ROW = r"\\{\\{Intents Table/row([\\s\\S]*?)\\}\\}"` 是非贪婪的，而 `{{Asc|2|4}}` 本身就含 `}}`
⇒ 每一行的 body 在**第一个** Asc 模板处被切断 ⇒ `ASC.findall` 只拿到第一个档位。
后果是 18 条 `MISMATCH`（wiki 写 A2/A17 两档，脚本只读到 A2，于是说"阈值不一致"）和
3 条 `MISSING`（`darkling.nip` / `louse_red.bite` / `louse_green.bite` —— 那三档其实在
遭遇记录的 `Rolls` 里）全是假报告。

这是"工具报成功/报问题，被测对象其实没问题"的那一类：不改的话，下一个人会去补不存在的档位。
§328 的闸门 `[7b]`（`sts_content_check.py`）已经用"逐行扫到下一个 row/end"的正确写法，
这个脚本改成同一口径，并把"由 `Rolls` 表达"的档位单独归一类。
"""

import io

PATH = 'native/audit_asc_gap.py'

OLD_ROWS = '''ROW = re.compile(r"\\{\\{Intents Table/row([\\s\\S]*?)\\}\\}", re.S)'''

NEW_ROWS = '''# ⚠️ §330：**不要**用 `\\{\\{Intents Table/row([\\s\\S]*?)\\}\\}` —— 非贪婪匹配会在第一个
# `{{Asc|2|4}}` 的 `}}` 处截断，于是每行只读到**第一个**升档。改成按"下一个 row / end"切块。
ROW_SPLIT = re.compile(r"\\{\\{Intents Table/(?:row|end)")'''

OLD_LOOP = '''        for match in ROW.finditer(text):
            body = match.group(1)
            move = re.search(r"\\|\\s*Name\\s*=\\s*([^|\\n]+)", body)
            if not move:
                continue'''

NEW_LOOP = '''        # 每个 row 的 body = 从它自己的 `row` 标记到下一个 `row`/`end` 标记之间。
        marks = [m.start() for m in ROW_SPLIT.finditer(text)]
        for index, start in enumerate(marks):
            end = marks[index + 1] if index + 1 < len(marks) else len(text)
            body = text[start:end]
            match = re.match(r".*", body)  # 占位，保持下面的缩进形状
            move = re.search(r"\\|\\s*Name\\s*=\\s*([^|\\n]+)", body)
            if not move:
                continue'''
OLD_BOXLOOP = '''            box_name = '?'
            for start, box in boxes:
                if start > match.start():
                    break'''
NEW_BOXLOOP = '''            box_name = '?'
            for box_start, box in boxes:
                if box_start > start:
                    break'''

OLD_APPEND = '''            thresholds = sorted({int(t) for t in ASC.findall(body)})
            if thresholds:
                out.append((name[:-4], box_name, move.group(1).strip(), thresholds))'''

NEW_APPEND = '''            thresholds = sorted({int(t) for t in ASC.findall(body)})
            if thresholds:
                out.append((name[:-4], box_name, move.group(1).strip(), thresholds))'''

# 由 `ENCT.Enemies[].Rolls` 表达的升档（骰子范围），单独归一类。
OLD_MAIN_HEAD = '''def main():
    rows = wiki_rows()
    doc, monsters, actions = content_index()
    missing, mismatch, extra, unresolved = [], [], [], []'''

NEW_MAIN_HEAD = '''def roll_levels(doc):
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


def main():
    rows = wiki_rows()
    doc, monsters, actions = content_index()
    rolls = roll_levels(doc)
    missing, mismatch, extra, unresolved, via_rolls = [], [], [], [], []'''

OLD_VERDICT = '''        have = [v['AscensionMin'] for v in (row.get('ProgramAsc') or [])]
        if not have:
            missing.append((row['Id'], thresholds))'''

NEW_VERDICT = '''        have = [v['AscensionMin'] for v in (row.get('ProgramAsc') or [])]
        if not have:
            # §330：骰子范围（`Rolls`）是**另一条载体** —— 那一档已经表达了，不是缺口。
            if set(thresholds) <= rolls.get(monster, set()):
                via_rolls.append((row['Id'], thresholds))
                continue
            missing.append((row['Id'], thresholds))'''

OLD_REPORT = '''    print('MISMATCH (阈值不一致): %d' % len(mismatch))'''

NEW_REPORT = '''    if via_rolls:
        print('VIA_ROLLS (档位由 `ENCT.Enemies[].Rolls` 表达，不是缺口): %d' % len(via_rolls))
        for action_id, thresholds in via_rolls:
            print('   %-34s wiki=%s' % (action_id, thresholds))
    print('MISMATCH (阈值不一致): %d' % len(mismatch))'''


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()
t = sub(t, OLD_ROWS, NEW_ROWS, 'regex')
t = sub(t, OLD_LOOP, NEW_LOOP, 'loop')
t = sub(t, OLD_BOXLOOP, NEW_BOXLOOP, 'box loop')
t = sub(t, OLD_MAIN_HEAD, NEW_MAIN_HEAD, 'main head')
t = sub(t, OLD_VERDICT, NEW_VERDICT, 'verdict')
t = sub(t, OLD_REPORT, NEW_REPORT, 'report')
# 顺手删掉一段永远不执行的死代码（`for r in []`）。
t = sub(t, '''    for row in doc['EnemyActions']:
        have = [v['AscensionMin'] for v in (row.get('ProgramAsc') or [])]
        if not have:
            continue
        print_id = row['Id']
        if not any(r['Id'] == print_id for r in []):
            pass
''', '', 'dead loop')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('audit_asc_gap.py: row parsing fixed + VIA_ROLLS')
