"""§319：内容门再加一条 —— **条件与效果必须指同一个类型**。

`Falling` 的三个选项是"条件 `card_tag has X` + 效果 `remove_card_random:Y`"。两者写岔
（例如 Skill 的按钮删 Attack）在**任何一侧**都不会红：条件是内容之间的���对，效果是内核
按自己的载荷办事 —— 页面上只是"点了 skill 掉了一张攻击"。这条判据把它钉住。
"""

import io

PATH = 'native/sts_content_check.py'

OLD = """    ok("event pools", "act1=%d act2=%d act3=%d"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or [])))"""

NEW = '''    ok("event pools", "act1=%d act2=%d act3=%d"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or [])))

    # §319：`card_tag` 条件与 `remove_card_random:` 效果**必须指同一个类型**。
    # 两者写岔不会在别处红（条件只是"画不画按钮"，效果由内核按自己的载荷办），
    # 页面上表现为"点了 Land 掉了一张攻击"。
    paired = 0
    for node in doc.get("EventNodes") or []:
        for index, option in enumerate(node.get("Options") or []):
            where = "EventNodes.%s.Options%d" % (node.get("Id"), index)
            wants = set()
            for atom in option.get("Requires") or []:
                if isinstance(atom, dict) and atom.get("Kind") == "card_tag" \
                        and atom.get("Op") == "has":
                    wants.add(atom.get("Id"))
            kinds = set()
            for atom in option.get("Effects") or []:
                text = atom.get("Effect") if isinstance(atom, dict) else None
                if isinstance(text, str) and text.startswith("remove_card_random:"):
                    kinds.add(text.split(":", 1)[1])
            if kinds and wants != kinds:
                fail(where, "条件要 %s，效果却删 %s —— 两组类型必须逐个相等"
                     % (sorted(wants) or "无", sorted(kinds)))
            if kinds:
                paired += len(kinds)
    ok("remove_card_random pairing", "%d option(s) pair a `card_tag` condition with the "
                                     "same type in its effect" % paired)'''


def main():
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(OLD) == 1, 'anchor'
    assert 'remove_card_random pairing' not in t, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(OLD, NEW))
    print('pairing check added')


main()
