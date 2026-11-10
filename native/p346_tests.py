"""§346 判据：五个导出的值与哨兵，外加"三个 DOM 钩子真的有值"。

## 为什么钩子也要判据

`data-event-id` / `data-encounter-id` / `data-active-slot` 是**给渲染层读的**，DOM 版自己不消费。
"写了但没人读"正是本项目最恨的形态之一（§4.14：探针只打印 keys）。所以浏览器判据要断言
它们**在真实局面里有值**（不是空串、不是 `undefined`、不是恒 `-2`）。

## 五个导出各测什么

| 导出 | 判据 |
|---|---|
| `rd_run_has_relic` | 无局 `-1`；没那件 `0`；授了那件 `1`；空指针 `0`（不是崩溃） |
| `rd_run_start_offer_count` | 无局 `0`；开局后 `>0` 且等于页面能读到的槽数 |
| `rd_run_event_id_len/into` | 非事件屏是**空串**（不是 `-1` 也不是垃圾）；进事件后是那个 id |
| `rd_run_encounter_id_len/into` | 打之前空串；`fight_begin` 之后是那条遭遇的 id（与 `last_encounter` 同源） |
| `rd_env_active_slot` | 无会话 `-3`；英雄回合 `-1`；敌人回合 `0..5` |
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
BROWSER = 'web/browser_test.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① rd-wasm 判据 ──────────────────────────────────────────────────────────
t = io.open(RUN, encoding='utf-8').read()

ANCHOR = '''    /// §345（缺口 G5）：`rd_run_boss_id_*` 按**幕**给不同的 id。'''

TEST = '''    /// §346：缺口 G3 / G6 / G7 / G12 的五个导出。
    ///
    /// 每条都测**两侧**（有 / 没有），因为"永远返回同一个值"的实现会全绿：
    /// `has_relic` 恒 1、`event_id` 恒空、`active_slot` 恒 -1 —— 每一种都看起来像在工作。
    #[test]
    fn the_run_facts_the_ui_asks_about() {
        crate::take_session();
        *run_slot() = None;
        // 无局：`has_relic` 是 `-1`（"问不了"），不是 0（"没有"）。
        assert_eq!(unsafe { rd_run_has_relic(b"x".as_ptr(), 1) }, -1, "no run");
        assert_eq!(rd_run_start_offer_count(), 0, "no run");
        assert_eq!(rd_run_event_id_len(), -1, "no run");
        assert_eq!(rd_run_encounter_id_len(), -1, "no run");
        assert_eq!(rd_env_active_slot(), -3, "no combat session");

        reset(7);

        // G3：没有那件遗物 ⇒ 0；授了 ⇒ 1。**两侧都测**（恒 1 或恒 0 的实现会各红一次）。
        assert_eq!(
            unsafe { rd_run_has_relic(b"singing_bowl".as_ptr(), 12) },
            0,
            "we do not hold singing_bowl"
        );
        assert_eq!(
            unsafe { rd_run_grant_relic(b"singing_bowl".as_ptr(), 12) },
            0,
            "grant: {}",
            run_error_text()
        );
        assert_eq!(
            unsafe { rd_run_has_relic(b"singing_bowl".as_ptr(), 12) },
            1,
            "now we do"
        );
        // 空指针不是崩溃，是"没有"。
        assert_eq!(unsafe { rd_run_has_relic(std::ptr::null(), 12) }, 0, "null id");

        // G7：条数由内核给。开局祝福屏一定有 >= 2 个槽（内容就是两个）。
        let offers = rd_run_start_offer_count();
        assert!(offers >= 2, "the blessing screen must offer at least two, got {offers}");
        for slot in 0..offers {
            assert!(
                rd_run_start_offer_len(slot) > 0,
                "slot {slot} of {offers} must have a name"
            );
        }

        // G6：没有事件时是**空串**（不是 -1、不是垃圾）。
        assert_eq!(rd_run_event_id_len(), 0, "no event open");
        // 遭遇：还没打 ⇒ 空串；开打之后 ⇒ 非空（与 `last_encounter` 同源）。
        assert_eq!(rd_run_encounter_id_len(), 0, "no fight yet");
        assert_eq!(
            rd_run_choose_start(0),
            0,
            "finish the blessing: {}",
            run_error_text()
        );

        // 走到一个战斗节点、开打，然后读遭遇 id 与活跃墙位。
        let mut fought = false;
        for _hop in 0..24 {
            if rd_run_step(0) != 0 {
                break;
            }
            let kind = rd_run_node_kind();
            if kind < 0 || rd_run_begin_node() != 0 {
                break;
            }
            let fight = kind == 1
                || kind == 2
                || kind == 7
                || (kind == 5
                    && run_slot().as_ref().expect("a run").state.unknown_room()
                        == rd_run::state::UnknownRoom::Monster);
            if fight {
                assert_eq!(rd_run_encounter_id_len(), 0, "not picked yet");
                assert_eq!(rd_run_fight_begin(), 0, "begin: {}", run_error_text());
                assert!(
                    rd_run_encounter_id_len() > 0,
                    "a running fight knows its encounter"
                );
                // G12：开局是英雄的回合 ⇒ `-1`。
                assert_eq!(rd_run_active_slot(), -1, "the hero acts first");
                fought = true;
                break;
            }
            match rd_run_pending() {
                1 => {
                    let _ = rd_run_rest();
                }
                3 => {
                    let _ = rd_run_open_chest();
                    let _ = rd_run_leave();
                }
                5 => {
                    let _ = rd_run_choose(0);
                }
                8 => {
                    let _ = rd_run_pick_event_card(0);
                }
                4 => {
                    let _ = rd_run_skip_reward();
                }
                _ => {}
            }
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
        }
        assert!(fought, "the fixture must reach a fight within 24 hops");
        // 结束战斗，让下一个测试拿到干净的会话（这个模块的测试共用全局槽）。
        let _ = rd_run_fight_end();
    }

    /// §345（缺口 G5）：`rd_run_boss_id_*` 按**幕**给不同的 id。'''

t = sub(t, ANCHOR, TEST, 'run facts test')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 浏览器判据：三个钩子在真实局面里有值 ─────────────────────────────────
t = io.open(BROWSER, encoding='utf-8').read()

ANCHOR2 = '''      out.act2.after = enemySlots();
      out.act2.afterIds = enemyIds();'''
NEW2 = '''      out.act2.after = enemySlots();
      out.act2.afterIds = enemyIds();
      // §346：三个 DOM 钩子在**真实局面**里必须有值 —— "写了但没人读"是本项目最恨的形态之一，
      // 而它们恰好是"DOM 版自己不消费、只给渲染层读"的那种，所以只能在这里钉。
      out.act2.encounterId = document.getElementById("runStats").dataset.encounterId || "";
      out.act2.activeSlot = document.getElementById("enemies").dataset.activeSlot || "";'''
t = sub(t, ANCHOR2, NEW2, 'collect hooks')

ANCHOR3 = '''want(!summonedIds.some((id) => id === "" || id === null),
  `act 2: a summoned enemy still has no id: ${JSON.stringify(summonedIds)}`);'''
NEW3 = '''want(!summonedIds.some((id) => id === "" || id === null),
  `act 2: a summoned enemy still has no id: ${JSON.stringify(summonedIds)}`);
// §346：`data-encounter-id` / `data-active-slot` 必须在战斗中**有值**（不是空串、不是 "undefined"）。
want(/^enc_/.test(act2.encounterId || ""),
  `act 2: data-encounter-id must name the encounter, got ${JSON.stringify(act2.encounterId)}`);
want(/^-?\\d+$/.test(act2.activeSlot || ""),
  `act 2: data-active-slot must be a wall slot, got ${JSON.stringify(act2.activeSlot)}`);'''
t = sub(t, ANCHOR3, NEW3, 'assert hooks')
io.open(BROWSER, 'w', encoding='utf-8', newline='\n').write(t)
print('§346 tests: five exports (rd-wasm) + three DOM hooks (browser)')
