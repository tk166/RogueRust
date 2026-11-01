"""§162: **extend the existing `check_invariants`, do not add a second validator.**

`RunState::check_invariants` already existed (spec §6.2: map validity, floor range with the boss
exception, health, container capacities, cursor/row agreement). Writing `validate` next to it was
the exact "two copies of one vocabulary" mistake this project keeps finding — the second copy drifts
and nothing goes red, because both are "a validator".

So: the new checks become part of `check_invariants`, and `archive::restore` calls that. The
new ones, each of which a real bug or a real attack can produce:

* `len` 之后必须是 EMPTY（§161.10 的 `remove_card` 尾槽）；
* 遗物不许重复；药水不超过腰带格数；
* `pending` 与所在房间一致（`Pending::room`）；
* 后续动作（`event_follow` / `blessing_follow`）必须挂在对应问句上；
* `start_offers` 在表内；商店/奖励屏的行是活的；
* gold / removed_cards / act / ascension / potion_chance / rarity_offset 的取值范围。
"""
import io

PATH = "kernel/rd-run/src/state.rs"


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- 1. drop the duplicate `validate`, keep the doc that says why it is one function -----
    start = text.index("    /// **这一局自相矛盾吗？**（§162，REVIEW §六 第 4 步的 P1）")
    # `node_at_cursor` comes after `validate`; keep it (it is used by the checks).
    keep_from = text.index("    /// 游标下这个节点的**类型**；哨兵按 Boss 算", start)
    extra_start = text.index("        // ---- 标量 ----", start)
    extra_end = keep_from
    extra = text[extra_start:extra_end]
    text = text[:start] + text[keep_from:]

    # ---- 2. append the new checks to `check_invariants`, before its final `Ok(())` ----------
    anchor = '''            if row as i32 + 1 != self.floor {
                return Err(RunError::Invariant("floor does not match the node's row"));
            }
        }
        Ok(())
    }'''
    assert text.count(anchor) == 1, text.count(anchor)

    # the body lifted out of `validate`, minus the parts `check_invariants` already does
    body = extra
    for duplicate in (
        '''        if self.health_max <= 0 {
            return Err(RunError::Invariant("health_max must be positive"));
        }
        if self.health < 0 || self.health > self.health_max {
            return Err(RunError::Invariant("health must be in 0..=health_max"));
        }
''',
        '''        // ---- 游标与楼层 -------------------------------------------------------------------
        let top = crate::map::ROWS as i32 + 1;
        if self.floor < 0 || self.floor > top {
            return Err(RunError::Invariant("floor must be in 0..=ROWS+1"));
        }
''',
    ):
        assert body.count(duplicate) == 1, duplicate[:50]
        body = body.replace(duplicate, "")

    # the cursor/floor part that `check_invariants` already has, but sharper: keep only the
    # `node < 0` half (`check_invariants` already ties the rest together).
    old_cursor = '''        if self.node < 0 {
            // 「还没出发」：楼层必须是 0，而且没有问句（`?` 房之前什么都没有）。
            if self.floor != 0 {
                return Err(RunError::Invariant("no cursor means floor 0"));
            }
        } else {
            let node = u8::try_from(self.node)
                .map_err(|_| RunError::Invariant("cursor is not a node index"))?;
            if node == crate::map::BOSS_NODE {
                if self.floor != top {
                    return Err(RunError::Invariant("the boss sentinel is the floor past the map"));
                }
            } else {
                let (row, _) = self
                    .map
                    .locate(node)
                    .ok_or(RunError::Invariant("cursor is not on the map"))?;
                if self.floor != row as i32 + 1 {
                    return Err(RunError::Invariant("floor disagrees with the cursor's row"));
                }
            }
        }
'''
    assert body.count(old_cursor) == 1
    body = body.replace(old_cursor, "")

    new_body = body.strip("\n")
    # the "past len must be EMPTY" part is the §162 addition people will look for: name it.
    new_body = new_body.replace(
        "        // ---- 三个定容容器：`len` 之前有内容、之后是空的 -------------------------------------",
        "        // ---- `len` 之前有内容、之后是空的（§161.10 的 `remove_card` 尾槽就是这个漏的）----",
    )

    replacement = anchor.replace(
        "        Ok(())\n    }",
        "        }\n" + new_body + "\n        Ok(())\n    }",
    )
    # `check_invariants` already closed its `else` block; the anchor includes that brace.
    replacement = replacement.replace(
        "            }\n        }\n        }\n",
        "            }\n        }\n",
        1,
    )
    text = text.replace(anchor, replacement)

    # ---- 3. restore asks `check_invariants` ------------------------------------------------
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("validate folded into check_invariants")


if __name__ == "__main__":
    main()
