"""§286 内容门：`Branches`（含 A15 版）、`Fight`、段的 `Effects`（进入效果）。

判据（每条都对应一个"静默无效"的形状）：

* `Branches` 每项是 `{Weight, Next}`；权重 1..=100；**和恰好 100**（和不是 100 的掷骰
  是一颗永远落不到最后一档的骰子）；条数 2..=4；`Next` 必须存在，且参与可达性。
* `Chance`/`NextFail`（§285 的旧形状）**已经不存在** —— 留着会被当成未知字段静默忽略。
* `Fight` ∈ {monster, elite}，且**不许**和 `Next`/`Branches` 同时出现（战斗收尾整个事件）。
* 段的 `Effects` / `EffectsAsc` 走**同一个**效果词表；**不许改牌**（改牌会变成待答问题，
  而问题队列只有一个位置）。
"""
import io

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ── ① 旧形状 `Chance`/`NextFail` 必须彻底消失
    old = '''            # §285：`Chance` 与 `NextFail` **必须成对**，而且两条边都要算可达。
            chance = option.get("Chance")
            fail_to = option.get("NextFail") or ""
            if (chance is None) != (fail_to == ""):
                fail(label, "`Chance` and `NextFail` must come together (Chance=%r, NextFail=%r)"
                     % (chance, fail_to))
            if chance is not None and not (isinstance(chance, int) and 1 <= chance <= 100):
                fail(label + ".Chance", "must be 1..=100, got %r" % (chance,))
            for key in ("Next", "NextFail"):
                nxt = option.get(key) or ""
                if not nxt:
                    continue
                if nxt not in node_ids:
                    fail("%s.%s" % (label, key), "names %r, which is not in EventNodes" % (nxt,))
                else:
                    reached.add(nxt)'''
    new = '''            # §286：`Branches`（权重表）取代了 §285 的 `Chance`/`NextFail`。
            # 旧形状**必须报错**而不是被忽略：留着它的人以为概率还在，而内核只看 `Branches`。
            for dead in ("Chance", "NextFail"):
                if dead in option:
                    fail(label, "`%s` is gone (§286) -- use `Branches`" % dead)
            # §286：`Fight` 与后继**互斥** —— 战斗结算整个房间，之后不回到事件。
            fight = option.get("Fight")
            if fight is not None:
                if fight not in ("monster", "elite"):
                    fail(label + ".Fight", "must be `monster` or `elite`, got %r" % (fight,))
                if (option.get("Next") or "") or option.get("Branches"):
                    fail(label, "`Fight` ends the event, so it cannot also have Next/Branches")
            for key in ("Branches", "BranchesAsc"):
                table = option.get(key)
                if table is None:
                    continue
                if not isinstance(table, list) or not (2 <= len(table) <= 4):
                    fail("%s.%s" % (label, key), "must be a list of 2..=4 branches")
                    continue
                total = 0
                for index, branch in enumerate(table):
                    where = "%s.%s[%d]" % (label, key, index)
                    if not isinstance(branch, dict):
                        fail(where, "must be an object {Weight, Next}")
                        continue
                    weight = branch.get("Weight")
                    if not isinstance(weight, int) or not (1 <= weight <= 100):
                        fail(where + ".Weight", "must be 1..=100, got %r" % (weight,))
                        continue
                    total += weight
                    nxt = branch.get("Next") or ""
                    if not nxt:
                        fail(where + ".Next", "is required")
                    elif nxt not in node_ids:
                        fail(where + ".Next", "names %r, which is not in EventNodes" % (nxt,))
                    else:
                        reached.add(nxt)
                if total != 100:
                    # 和不是 100 时，掷骰的最后一档会吸收零头 —— 那不是"接近"，是
                    # 一个概率表和它写的数字不一致。
                    fail("%s.%s" % (label, key),
                         "weights must sum to exactly 100, got %d" % total)
            nxt = option.get("Next") or ""
            if nxt:
                if nxt not in node_ids:
                    fail(label + ".Next", "names %r, which is not in EventNodes" % (nxt,))
                else:
                    reached.add(nxt)'''
    s = patch(s, old, new)

    # ── ② 段的进入效果：同一个词表，但不许改牌
    old = '''        # §285：入口段通常要两个选项'''
    new = '''        # §286：段的**进入效果**（`Effects` / `EffectsAsc`）。词表与选项共用一套检查，
        # 所以这里先把它们当作"一个没有选项的虚拟选项"过一遍词表 —— 但**改牌禁止**。
        for key in ("Effects", "EffectsAsc"):
            entry = node.get(key)
            if entry is None:
                continue
            if not isinstance(entry, list) or not entry:
                fail("%s.%s" % (label_root, key), "must be a non-empty list")
                continue
            for index, spec in enumerate(entry):
                where = "%s.%s[%d]" % (label_root, key, index)
                if not isinstance(spec, dict):
                    fail(where, "must be an object {Effect, Amount}")
                    continue
                word = spec.get("Effect") or ""
                if word.split(":")[0] in ("remove_card", "upgrade_card", "transform_card"):
                    fail(where, "a step-entry effect cannot change the deck (the answer queue "
                                "has one slot and the option already used it)")
        # §285：入口段通常要两个选项'''
    s = patch(s, old, new)

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('gate: Branches / Fight / step-entry effects')
    print('NEXT: 词表检查要认识 Branches 的 Next 目标（已在可达性里）；段的 Effects 还要走词表')


main()
