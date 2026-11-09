"""§311（三）：把 `enc_sentry_and_spheric` 拿掉，并给 `spheric_guardian` 登记"血量不随升阶变"。

为什么要拿掉 Sentry 那条（不是偷懒，是**清单模型**不允许）：

`check_ascension_health` 按**池子档位**钉一条 `MaxHealthAsc`：精英池 A8、普通池 A7，而一条
怪物行只允许**一个** `MaxHealthAsc` 行。Sentry 的 wiki 数字是"38-42，**A8** 起 39-45"
（`Sentry` 页 + `SlaySpireDB` 两处），它同时出现在 Act 1 的**精英**池（三只）与 Act 2 的
**普通**池（一只 + Spheric）—— 同一个 id 被要求同时钉 A7 与 A8，两条不可能同时成立。

⇒ 这一条留到"同一只怪物跨档位"这件事被建模之后再做（`docs/sts-wiki-gap.md` §D.3 记一笔）。
Spheric Guardian 单独那条仍然做（它只出现在普通池）。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    before = len(doc['Encounters'])
    doc['Encounters'] = [e for e in doc['Encounters']
                         if e['Id']['Value'] != 'enc_sentry_and_spheric']
    pool = doc['EncounterTables']['Weak2']
    doc['EncounterTables']['Weak2'] = [row for row in pool
                                       if row['Id'] != 'enc_sentry_and_spheric']
    assert len(doc['Encounters']) == before - 1
    assert 'enc_sentry_and_spheric' not in [r['Id'] for r in doc['EncounterTables']['Weak2']]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

    text = io.open(CHECK, encoding='utf-8').read()
    old = "    'maw': 'wiki The Maw: max HP does not change with ascension',\n}"
    new = ("    'maw': 'wiki The Maw: max HP does not change with ascension',\n"
           "    # §311：wiki 的 Spheric Guardian 只有 `HP 20` 一个数（没有 `78-83 7` 那样的第二列），\n"
           "    # 所以它的血量不随升阶变 —— 给它钉一个数等于发明一个数。\n"
           "    'spheric_guardian': 'wiki Spheric Guardian: HP 20, no AscHP column',\n}")
    assert text.count(old) == 1
    text = text.replace(old, new)

    old_pool = ('              "enc_chosen_and_byrd", "enc_cultist_and_chosen", "enc_sentry_and_spheric",\n'
                '              # §282: Act 2 的普通怪 Snecko（`Confusion` 的载体）。')
    new_pool = ('              "enc_chosen_and_byrd", "enc_cultist_and_chosen",\n'
                '              # §282: Act 2 的普通怪 Snecko（`Confusion` 的载体）。')
    assert text.count(old_pool) == 1
    text = text.replace(old_pool, new_pool)

    old_inv = ('    "enc_sentry_and_spheric": ["sentry_1", "spheric_guardian"],\n')
    assert text.count(old_inv) == 1
    text = text.replace(old_inv, '')
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('sentry encounter dropped; spheric pinned as no-asc')


main()
