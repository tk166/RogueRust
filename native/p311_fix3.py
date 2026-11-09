"""§311（九）：`enc_byrds` 不能在两个池子里 —— 内核有这条不变量。

`content::tests::the_encounter_pools_are_readable` 当场红：

    `enc_byrds` is in two pools -- an encounter belongs to exactly one

这条不变量是对的（一条遭遇进两个池子会让权重被算两遍）。所以 Act 2 的三只 byrd 用**自己的**
一条遭遇 `enc_city_byrds`（敌人记录从 `enc_byrds` 原样复制，HP/升阶数字因此天然一致）。

⚠️ 这不是"多写一条"，而是模型边界：wiki 的两幕确实都有 "3 Byrds"，而内核把"遭遇"与"池子"
绑成一件事。记在 `docs/sts-wiki-gap.md` §D.3.1。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    byrds = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_byrds')
    assert not any(e['Id']['Value'] == 'enc_city_byrds' for e in doc['Encounters'])
    city = dict(byrds)
    city['Id'] = {'Value': 'enc_city_byrds'}
    doc['Encounters'].append(city)

    for row in doc['EncounterTables']['Weak2']:
        if row['Id'] == 'enc_byrds':
            row['Id'] = 'enc_city_byrds'
    assert not any(r['Id'] == 'enc_byrds' for r in doc['EncounterTables']['Weak2'])
    assert any(r['Id'] == 'enc_byrds' for r in doc['EncounterTables']['Weak3'])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

    text = io.open(CHECK, encoding='utf-8').read()
    old_inv = ('    # §311：wiki 的 "3 Byrds" 是**三只**（这一条内容原先只写了一只，'
               '同时影响第三幕的池子）。\n    "enc_byrds": ["byrd", "byrd", "byrd"],')
    new_inv = ('    # §311：wiki 的 "3 Byrds" 是**三只**（这一条内容原先只写了一只，'
               '同时影响第三幕的池子）。\n'
               '    "enc_byrds": ["byrd", "byrd", "byrd"],\n'
               '    # 两幕都有 "3 Byrds"，而内核要求"一条遭遇只属于一个池" ⇒ Act 2 用自己的一条\n'
               '    # （敌人记录从 `enc_byrds` 复制，HP/升阶数字因此一致）。\n'
               '    "enc_city_byrds": ["byrd", "byrd", "byrd"],')
    assert text.count(old_inv) == 1
    text = text.replace(old_inv, new_inv)
    text = text.replace('"enc_byrds",\n              "enc_chosen_and_byrd"',
                        '"enc_city_byrds",\n              "enc_chosen_and_byrd"')
    assert '"enc_city_byrds",\n              "enc_chosen_and_byrd' in text
    old_count = '    "encounters": 49,'
    assert text.count(old_count) == 1
    text = text.replace(old_count, '    "encounters": 50,')
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('enc_city_byrds added; pool + inventory updated')


main()
