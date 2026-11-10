"""§341：`rd_run_in_fight()` —— 给 UI 场景表一个**内核判据**（八轮 Review 3.1 / 缺口 G16）。

## 为什么需要

UI 的场景表里"战斗待开始"（SC-03）与"战斗中"（SC-03b）必须互斥。而内核此前**没有任何一格**
能区分它们：

* `rd_run_pending()` 在两种情况下都是 `0`；
* `rd_run_node_resolved()` 在战斗中仍然是 false（要等 `fight_end`）；
* `rd_env_done()` 在**没有会话**时返回 `1`（"结束了"），所以它不能反过来说"有没有战斗"；
* `rd_env_beat_count()` 无会话返回 `-1`，能用但是**间接**（"没有 beat" ≠ "没有战斗"）。

于是"未开始"只能是页面自己记的标志（`web/index.html` 的 `mode`）—— 场景表没法变成纯函数。

## 判据

`rd_wasm::run::tests::the_run_layer_reports_whether_a_fight_is_running`：
`-1`（没有局）→ `0`（地图上）→ `1`（`fight_begin` 之后）→ `0`（`fight_end` 之后）。
四态全覆盖，而且**与 `archive_fill` 的拒绝判据同一个字段**（战斗中导不出存档）。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'
SMOKE = 'web/smoke.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① smoke.mjs 的 REQUIRED 清单（手抄的第二份，加导出要抄两次）─────────────────
t = io.open(SMOKE, encoding='utf-8').read()
if 'rd_run_in_fight' not in t:
    t = sub(t, '''  "rd_env_card_kind", "rd_run_card_kind", "rd_run_node_resolved", "rd_run_boss_beaten",''',
        '''  "rd_env_card_kind", "rd_run_card_kind", "rd_run_node_resolved", "rd_run_boss_beaten",
  // §341: "有没有一场正在打的战斗" —— UI 场景表里 SC-03（待开始）与 SC-03b（战斗中）
  // 的唯一内核判据（`rd_env_done()` 在**没有会话**时返回 1，所以它不能反过来说）。
  "rd_run_in_fight",''', 'smoke REQUIRED')
io.open(SMOKE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② rd-wasm 判据 ──────────────────────────────────────────────────────────
t = io.open(WASM, encoding='utf-8').read()

ANCHOR = '''    /// §336：`fight_begin` 那一条记录的第 5 列是**战斗状态**的 `hash_full`。'''

TEST = '''    /// §341：`rd_run_in_fight()` —— 四态全覆盖。
    ///
    /// 为什么这条值得一个判据：它是 UI 场景表里 SC-03（战斗**待开始**）与 SC-03b（战斗中）
    /// 的**唯一**内核判据。此前页面只能自己记一个 `mode` 标志，于是"场景"不是状态的函数
    /// 而是**历史的函数** —— 3D 重写必须重新发明它（八轮 Review 3.1）。
    ///
    /// 四态：没有局 `-1` → 地图上 `0` → `fight_begin` 之后 `1` → `fight_end` 之后 `0`。
    /// 顺带钉住"它与存档拒绝判据是同一个字段"：战斗中 `archive_fill` 必须拒绝。
    #[test]
    fn the_run_layer_reports_whether_a_fight_is_running() {
        crate::take_session();
        *run_slot() = None;
        assert_eq!(rd_run_in_fight(), -1, "no run at all");

        reset(7);
        assert_eq!(rd_run_in_fight(), 0, "a fresh run is on the map, not in a fight");

        // 走到一个战斗节点并开打。
        let mut begun = false;
        for hop in 0..24 {
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
                assert_eq!(rd_run_in_fight(), 0, "hop {hop}: not in a fight yet");
                assert_eq!(rd_run_fight_begin(), 0, "hop {hop}: begin");
                assert_eq!(rd_run_in_fight(), 1, "hop {hop}: a fight is running now");
                // 同一个字段还被存档那条判据用着：战斗中导不出存档。
                assert_eq!(
                    rd_run_archive_fill(),
                    -2,
                    "the same flag refuses an archive mid-fight"
                );
                assert!(rd_run_fight_end() >= 0, "hop {hop}: end");
                assert_eq!(rd_run_in_fight(), 0, "hop {hop}: the fight is over");
                begun = true;
                break;
            }
            // 结算这一格，走到下一步（照抄 §336 那条判据的循环体）。
            match rd_run_pending() {
                1 => {
                    let _ = rd_run_rest();
                }
                2 => {
                    let _ = rd_run_leave();
                }
                3 => {
                    let _ = rd_run_open_chest();
                    let _ = rd_run_leave();
                }
                _ => {}
            }
            if kind == 4 {
                let _ = rd_run_choose(0);
            }
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            while rd_run_pending() == 8 {
                let _ = rd_run_pick_event_card(0);
            }
            if rd_run_action_count() == 0 && rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
        }
        assert!(begun, "the fixture must reach a fight within 24 hops");
    }

    /// §336：`fight_begin` 那一条记录的第 5 列是**战斗状态**的 `hash_full`。'''

t = sub(t, ANCHOR, TEST, 'in_fight test')
io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('smoke REQUIRED + rd-wasm test')
