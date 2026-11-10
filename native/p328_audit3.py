"""§328 审计（第三遍）：按 **wiki 页面里的节** 匹配，而不是按文件名。

快照是按**页面**存的：`slavers.txt` 里有 `= Blue Slaver =` / `= Red Slaver =` 两节，
`shapes.txt` 里可能有 Spiker/Repulsor/Exploder。所以匹配要三步：
1. 把每个 dump 按 `^= Name =$` 切成节（第一个 `=` 之前的部分算 `''` 节，装 infobox）；
2. 用遭遇记录里的 `DisplayName`（没有就用 id）去认领那一节；
3. 在那一节里用 `NameKey` 找意图行，数 `{{Asc|N|`。
"""

import io
import json
import os
import re

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
WIKI = 'native/wiki_asc'

ASC_RE = re.compile(r'\{\{Asc\|(\d+)\|')


def norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def split_sections(path):
    text = io.open(path, encoding='utf-8').read()
    sections = {}
    current = ''
    buf = []
    for line in text.splitlines():
        m = re.match(r'^=\s*([^=]+?)\s*=\s*$', line)
        if m:
            sections[current] = '\n'.join(buf)
            current = norm(m.group(1))
            buf = []
            continue
        buf.append(line)
    sections[current] = '\n'.join(buf)
    return sections


def rows_of(section_text):
    rows = {}
    current = None
    for line in section_text.splitlines():
        m = re.match(r'\|\s*Name\s*=\s*(.+?)\s*$', line)
        if m:
            current = norm(m.group(1))
            rows.setdefault(current, '')
            continue
        if current is None:
            continue
        m = re.match(r'\|\s*Effect\s*=\s*(.*)$', line)
        if m:
            rows[current] = m.group(1)
    return rows


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))

    # monster id -> 显示名（遭遇记录里有）
    display = {}
    for encounter in doc['Encounters']:
        for enemy in encounter['Enemies']:
            if enemy.get('DisplayName'):
                display.setdefault(enemy['Id'], enemy['DisplayName'])

    # 所有节：normalized 节名 -> rows
    all_sections = {}
    for name in sorted(os.listdir(WIKI)):
        if not name.endswith('.txt'):
            continue
        own = norm(name[:-4])
        for key, text in split_sections(os.path.join(WIKI, name)).items():
            key = key or own          # 首个节头之前 = 这个页面自己的怪物
            if key and key not in all_sections:
                all_sections[key] = (name, rows_of(text))

    no_section = []
    missing = []
    checked = 0
    for action in doc['EnemyActions']:
        monster = action['Id'].split('.')[0]
        key = norm(display.get(monster, monster))
        hit = all_sections.get(key)
        if hit is None:
            # 兜底：节名与 id 互相包含（`redslaver` vs `slaverred`、`acid_slime` 这类同页怪物）
            for cand, value in all_sections.items():
                if key in cand or cand in key:
                    hit = value
                    break
        if hit is None:
            no_section.append(monster)
            continue
        file_name, rows = hit
        name = action.get('NameKey') or action['Id'].split('.', 1)[1]
        effect = rows.get(norm(name))
        if effect is None:
            continue
        checked += 1
        wiki_levels = sorted({int(x) for x in ASC_RE.findall(effect)})
        if not wiki_levels:
            continue
        have = sorted({int(r['AscensionMin']) for r in (action.get('ProgramAsc') or [])})
        if set(wiki_levels) - set(have):
            missing.append((action['Id'], file_name, wiki_levels, have, effect.strip()[:130]))

    print('按节匹配到意图行的动作：%d' % checked)
    print('认不出节的怪物 %d 个：%s' % (len(set(no_section)), sorted(set(no_section))))
    print('wiki 有升档、内容缺档：%d' % len(missing))
    for action_id, file_name, wiki_levels, have, effect in missing:
        print('  %-32s %-22s wiki=%-9s content=%-9s %s'
              % (action_id, file_name, wiki_levels, have, effect))


main()
