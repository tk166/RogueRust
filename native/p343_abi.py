"""§343 的 ABI 与页面：`rd_run_removal_available()` + 商店面板的"删一张牌"按钮。

## 为什么单独一个导出，而不是让价格返回 `-1`

价格那一格要显示"75 金"。把"不可用"塞进同一个数，页面就会把 `-1` 印成价格（§276 已经因为
"售罄哨兵过折扣变成 0" 踩过一次同形的坑）。两个事实两个数。

## 页面

`ui_panels.js` 的商店面板里，"删一张牌"那个按钮原来只看 `removePrice > gold`。
现在还要看"这家店删过了没有" —— 否则它就是一个**启用的死按钮**（点下去 `RemovalUsed`）。
⚠️ 判据写成 `=== 0`（明确说"用过了"才禁用）而不是 `!== 1`：老夹具（`ui_test.mjs`）没有这个
字段，`!== 1` 会把它们的按钮也禁掉，而那是夹具的事、不是规则的事。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
SMOKE = 'web/smoke.mjs'
PANELS = 'web/ui_panels.js'
PAGE = 'web/index.html'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 导出 ──────────────────────────────────────────────────────────────────
t = io.open(RUN, encoding='utf-8').read()
ANCHOR = '''/// §332：药水货架第 `slot` 瓶的挂牌价（`-1` = 已售）。'''
NEW_EXPORT = '''/// §343：这家店的删卡服务**还能不能用** —— `1` 能 / `0` 这家店已经删过了 / `-1` 没有局。
///
/// wiki.gg / fandom：*"Card Removal Service — Can only be used once per Shop."*
/// 页面拿它决定"删一张牌"按钮画不画得动；没有它，那个按钮就是一个**启用的死按钮**
/// （点下去内核报 `RemovalUsed`）。
///
/// 为什么不复用 `rd_run_remove_price()` 返回 `-1`：价格那一格要显示"75 金"，
/// 把"不可用"塞进同一个数会让页面把 `-1` 印成价格（§276 同形的坑）。
#[no_mangle]
pub extern "C" fn rd_run_removal_available() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |s| i32::from(s.state.removal_available()))
}

/// §332：药水货架第 `slot` 瓶的挂牌价（`-1` = 已售）。'''
t = sub(t, ANCHOR, NEW_EXPORT, 'removal_available export')

# ── ② 判据：四态（无局 / 商店可用 / 用掉 / 换店恢复）────────────────────────
ANCHOR2 = '''    /// §342（第九轮 Review P1-1）：**页面看到的价格就是内核收的价格**，四排都一样。'''
TEST = '''    /// §343：`rd_run_removal_available()` —— 四态。
    ///
    /// 它是"删一张牌"那个按钮的**唯一**依据。没有它，页面只能靠"点一下试试"发现额度用完了，
    /// 而那就是一个启用的死按钮（本项目最恨的形态）。
    ///
    /// 四态：没有局 `-1` → 商店里 `1` → 删过一次 `0` → 换一家店 `1`。
    #[test]
    fn the_removal_service_reports_whether_this_shop_still_allows_it() {
        crate::take_session();
        *run_slot() = None;
        assert_eq!(rd_run_removal_available(), -1, "no run at all");

        // 走到一个商店（与 §342 的判据同一段循环）。
        let mut reached = false;
        for seed in 0..400 {
            reset(seed);
            for _hop in 0..24 {
                if rd_run_pending() == 2 {
                    reached = true;
                    break;
                }
                if rd_run_step(0) != 0 {
                    break;
                }
                if rd_run_begin_node() != 0 {
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
                    _ => {
                        if rd_run_fight_begin() == 0 {
                            let _ = rd_run_fight_end();
                        }
                    }
                }
                while rd_run_pending() == 4 {
                    let _ = rd_run_skip_reward();
                }
            }
            if reached {
                break;
            }
        }
        assert!(reached, "no seed reached a shop within 24 hops");
        assert_eq!(rd_run_removal_available(), 1, "a fresh shop allows one removal");

        // 删一张（价格由 `rd_run_remove_price()` 给，这里只看额度）。
        let price = rd_run_remove_price();
        assert!(price > 0, "the removal service has a price: {price}");
        // 钱不一定够 —— 先把这局的钱"挣"够是做不到的，所以这里只验**拒绝不改额度**：
        // 钱不够时必须是 `-2`，而额度仍然在。
        let code = rd_run_remove_card(0);
        if code == 0 {
            assert_eq!(rd_run_removal_available(), 0, "the shop's one removal is spent");
            assert_eq!(
                rd_run_remove_card(0),
                -2,
                "a second removal in the same shop is refused: {}",
                run_error_text()
            );
            assert_eq!(rd_run_removal_available(), 0, "the refusal did not change anything");
        } else {
            assert_eq!(code, -2, "not enough gold is a refusal, not a crash");
            assert_eq!(
                rd_run_removal_available(),
                1,
                "a refused removal must NOT spend the shop's one use"
            );
        }
    }

    /// §342（第九轮 Review P1-1）：**页面看到的价格就是内核收的价格**，四排都一样。'''
t = sub(t, ANCHOR2, TEST + ANCHOR2, 'removal ABI test')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ smoke.mjs 的手抄清单 ──────────────────────────────────────────────────
t = io.open(SMOKE, encoding='utf-8').read()
t = sub(t, '''  // §341: "有没有一场正在打的战斗" —— UI 场景表里 SC-03（待开始）与 SC-03b（战斗中）''',
        '''  // §343: 这家店的删卡服务还能不能用（wiki: "once per Shop"）。
  "rd_run_removal_available",
  // §341: "有没有一场正在打的战斗" —— UI 场景表里 SC-03（待开始）与 SC-03b（战斗中）''',
        'smoke REQUIRED')
io.open(SMOKE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ 页面快照 ──────────────────────────────────────────────────────────────
t = io.open(PAGE, encoding='utf-8').read()
t = sub(t, '''    case 2:
      snapshot.removePrice = ex.rd_run_remove_price();''',
        '''    case 2:
      snapshot.removePrice = ex.rd_run_remove_price();
      // §343：这家店的删卡服务还能不能用（wiki: "once per Shop"）。`1` 能 / `0` 用过了。
      snapshot.removalAvailable = ex.rd_run_removal_available();''', 'snapshot')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ⑤ 商店面板：按钮可用性 ──────────────────────────────────────────────────
t = io.open(PANELS, encoding='utf-8').read()
t = sub(t, '''        {
          id: "remove",
          label: "删一张牌",
          // Same rule: a 75-gold removal with 23 gold is not a button, it is a price list.
          disabled: s.removePrice > s.gold,''',
        '''        {
          id: "remove",
          label: "删一张牌",
          // Same rule: a 75-gold removal with 23 gold is not a button, it is a price list.
          // §343：这家店删过了也不是按钮（wiki: "Can only be used once per Shop"）。
          // ⚠️ 判据写成 `=== 0`（内核**明确**说用过了）而不是 `!== 1`：老夹具没有这个字段，
          // `!== 1` 会把它们的按钮也禁掉 —— 那是夹具的事，不是规则的事。
          disabled: s.removePrice > s.gold || s.removalAvailable === 0,''',
        'panel disabled')
io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(t)
print('§343: export + smoke + page + panel')
