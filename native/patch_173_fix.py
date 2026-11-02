"""§173 fix: `CounterId` in the **node** is `{"value": …}`; in the **expression** it is a bare string.

What went wrong: `book_of_stabbing.multi_stab` wrote

    {"kind": "node.setCombatantCounter", "value": {"CounterId": "book_stab_uses", ...}}

while every existing node of that kind writes `"CounterId": {"value": "ritual_owner_turns"}`. The
compiler's field schema for that node treats the value as a *string literal object*, so a bare string
was encoded as something else -- which shifted the term stream and made an unrelated `ritual` trigger
read a non-term (`Ir(WrongKind("F_TERM"))`).

The same file had it the other way round for the **expression**: `combatantCounter`'s `CounterId` is a
plain string (see `standard.time_warp`). Two dialects, one field name; both spellings appear in the
shipped image, and this patch matches each where it belongs.

Also reverts my "fix" to `native/sts_content_check.py`: it assumed `CounterId["value"]` and I decided
the kernel's `str_field` proved it wrong. The kernel reads the **compiled** F_STR either way -- the JSON
spelling is the compiler's business, and the checker had it right.
"""
import io

ELITES = "native/patch_173_elites.py"
CHECK = "native/sts_content_check.py"

OLD_BUMP = '''    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": selector("sel.source", "Source"),
            "CounterId": name,
            "Amount": add(counter(name), const(1)),
            "Relative": False,
        },
    }'''

NEW_BUMP = '''    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": selector("sel.source", "Source"),
            # ⚠️ **node** 里的 `CounterId` 是 `{"value": …}`（与 `StatusDefinitionId` 同一个方言），
            # 而这个文件里 `combatantCounter` **表达式**的 `CounterId` 是裸字符串。写成裸字符串会
            # 让编码错位、后面的 term 全部移位 —— 表现为一条**无关的** status 触发器读到非 term。
            "CounterId": {"value": name},
            "Amount": add(counter(name), const(1)),
            "Relative": False,
        },
    }'''

OLD_CHECK = '''            # `CounterId` 是**裸字符串**（`NodeRef::str_field` 只接受 `F_STR`）；这一行原来写的是
            # `body["CounterId"]["value"]`，而在这之前没有任何内容用过这个节点 —— 于是它是**从没被
            # 执行过的死代码**，直到 §173 的 Book of Stabbing 第一次用它。两种形式都认，免得下次再撞。
            counter_id = body["CounterId"]
            if isinstance(counter_id, dict):
                counter_id = counter_id.get("value")
            facts.append(("counter", counter_id, amount(body["Amount"]),
                          body["Relative"], tgt(body["TargetSelector"])))'''

NEW_CHECK = '''            # `CounterId` 在**源 JSON** 里是 `{"value": …}`（节点字段的字符串字面量方言）。
            # §173 一度把它读成死代码并"修"成裸字符串 —— 那是错的：内核读的是**编译后**的 F_STR，
            # 源方言是编译器的事。这行原样保留。
            facts.append(("counter", body["CounterId"]["value"], amount(body["Amount"]),
                          body["Relative"], tgt(body["TargetSelector"])))'''


def main():
    for path, old, new in [(ELITES, OLD_BUMP, NEW_BUMP), (CHECK, OLD_CHECK, NEW_CHECK)]:
        text = io.open(path, encoding="utf-8").read()
        assert text.count(old) == 1, (path, text.count(old))
        io.open(path, "w", encoding="utf-8", newline="").write(text.replace(old, new))
    print("CounterId dialect fixed in the generator; the checker restored")


if __name__ == "__main__":
    main()
