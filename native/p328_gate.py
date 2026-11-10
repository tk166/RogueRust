"""§328 常设闸门：**wiki 快照里写了哪几档，内容就必须有那几档**。

为什么要有它：`INV_ASC_VARIANTS` 是人抄的清单，只能证明"内容与清单一致"。§327/§328 两次
审计都是靠**临时脚本**去比 wiki 快照才发现的偏差 —— 那意味着"下一次漏"没人会红。这道闸门把
那次比对变成常设的：读 `native/wiki_asc/*.txt` 的意图行（`| Name = …` / `| Effect = …`），
数 Effect 里的 `{{Asc|N|`，要求内容该动作的 `ProgramAsc` **至少**覆盖这几个等级。

三条"用别的机制表达"的显式白名单（每条都要写理由，否则就是拿白名单当静音开关）：

  * `darkling.nip`               —— A2 在遭遇记录的 `Rolls`（`roll.nip` 9-13）
  * `book_of_stabbing.multi_stab` —— A18 是 `book_stab_single_bump` 计数器
  * `the_guardian.twin_slam`     —— A9/A19 是 `mode_shift_budget` 计数器
"""

import io

PATH = 'native/sts_content_check.py'

ANCHOR = """def check_ascension_variants(doc):"""

FUNC = '''# §328: 升档等级**由 wiki 快照驱动**的那一份（`INV_ASC_VARIANTS` 是人抄的清单，这一份读 dump）。
#
# 键是动作 id，值是**理由**（空字符串不允许：白名单条目必须解释"哪一档由什么机制表达"）。
INV_ASC_LEVELS_BY_OTHER_MEANS = {
    'darkling.nip':
        "A2 lives in the encounter's `Rolls` (`roll.nip` 9-13), not in a `ProgramAsc` row",
    'book_of_stabbing.multi_stab':
        "A18 is the `book_stab_single_bump` counter on the encounter, not a `ProgramAsc` row",
    'the_guardian.twin_slam':
        "A9/A19 are the `mode_shift_budget` counter rows on the encounter, not `ProgramAsc`",
}

WIKI_ASC_DIR = "native/wiki_asc"


def _wiki_sections():
    """`native/wiki_asc/*.txt` → {节名(normalized): {行名(normalized): Effect 原文}}。

    快照是按 **wiki 页面** 存的（`slavers.txt` 里有 `= Blue Slaver =` / `= Red Slaver =` 两节），
    所以先按 `^= Name =$` 切节；第一个节头之前的部分算这个页面自己的怪物（单怪页面没有节头）。
    """
    import os
    import re
    sections = {}
    if not os.path.isdir(WIKI_ASC_DIR):
        return sections
    for name in sorted(os.listdir(WIKI_ASC_DIR)):
        if not name.endswith(".txt"):
            continue
        text = io.open(os.path.join(WIKI_ASC_DIR, name), encoding="utf-8").read()
        chunks = {}
        current = re.sub(r"[^a-z0-9]", "", name[:-4].lower())
        buf = []
        for line in text.splitlines():
            header = re.match(r"^=\\s*([^=]+?)\\s*=\\s*$", line)
            if header:
                chunks[current] = "\\n".join(buf)
                current = re.sub(r"[^a-z0-9]", "", header.group(1).lower())
                buf = []
                continue
            buf.append(line)
        chunks[current] = "\\n".join(buf)
        for key, body in chunks.items():
            rows = {}
            row = None
            for line in body.splitlines():
                named = re.match(r"\\|\\s*Name\\s*=\\s*(.+?)\\s*$", line)
                if named:
                    row = re.sub(r"[^a-z0-9]", "", named.group(1).lower())
                    rows.setdefault(row, "")
                    continue
                if row is None:
                    continue
                effect = re.match(r"\\|\\s*Effect\\s*=\\s*(.*)$", line)
                if effect:
                    rows[row] = effect.group(1)
            sections.setdefault(key, rows)
    return sections


def check_wiki_asc_levels(doc):
    """§328：wiki 的 `{{Asc|N|` 等级必须被内容的 `ProgramAsc` 覆盖（或由别的机制显式表达）。"""
    import re
    print("[7b] ascension levels from the wiki dump (port-plan.md §328)")
    sections = _wiki_sections()
    if not sections:
        print("  .. no wiki dumps; skipped")
        return
    # 怪物 id → 显示名（遭遇记录里有；`blue_slaver` 的 wiki 节叫 `Blue Slaver`）。
    display = {}
    for encounter in doc.get("Encounters") or []:
        for enemy in encounter_enemy_records(encounter):
            if enemy.get("DisplayName"):
                display.setdefault(enemy["Id"], enemy["DisplayName"])

    def norm(text):
        return re.sub(r"[^a-z0-9]", "", text.lower())

    checked = 0
    problems = 0
    for action in doc.get("EnemyActions") or []:
        aid = action["Id"]
        monster = aid.split(".")[0]
        key = norm(display.get(monster, monster))
        rows = sections.get(key)
        if rows is None:
            for candidate, value in sections.items():
                if key in candidate or candidate in key:
                    rows = value
                    break
        if rows is None:
            continue
        name = action.get("NameKey") or aid.split(".", 1)[1]
        effect = rows.get(norm(name))
        if effect is None:
            continue
        checked += 1
        wiki_levels = sorted({int(x) for x in re.findall(r"\\{\\{Asc\\|(\\d+)\\|", effect)})
        if not wiki_levels:
            continue
        have = {int(row["AscensionMin"]) for row in (action.get("ProgramAsc") or [])}
        gap = sorted(set(wiki_levels) - have)
        if not gap:
            continue
        if aid in INV_ASC_LEVELS_BY_OTHER_MEANS:
            continue
        problems += 1
        fail("asc.wiki." + aid,
             "the wiki names A%s, the content has A%s -- write the tier or add the action to "
             "`INV_ASC_LEVELS_BY_OTHER_MEANS` with the mechanism that expresses it"
             % (gap, sorted(have)))
    ok("ascension levels from the wiki", "%d intent rows compared, %d missing"
       % (checked, problems))


'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'def check_wiki_asc_levels' not in t, 'already patched'
t = t.replace(ANCHOR, FUNC + ANCHOR)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('checker: check_wiki_asc_levels inserted')
