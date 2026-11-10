"""§345 判据：显示层（纯函数）+ 内核的 Boss id。

## 显示层三条（`web/ui_test.mjs`，纯函数，不需要 wasm）

1. `prettifyId` 的五个规则各一条（分词、单字母、`+` 后缀、命名空间、空）；
2. `displayName` 的**优先级**：替换表 > 内核名 > 美化 id —— 这条顺序是"规避版权"能不能做到的
   分水岭（替换表必须能**覆盖**内核的名字）；
3. 替换表**命中时真的覆盖**（临时插一条 `slime_boss` 进去，断言它赢过内核名）。

## 内核一条（`rd-wasm`）

`rd_run_boss_id_*` 必须按幕给不同的 id（`Boss` / `Boss2` / `Boss3` 三个池）—— 写死的
"Slime Boss" 正是缺口 G5。
"""

import io

TEST = 'web/ui_test.mjs'
RUN = 'kernel/rd-wasm/src/run.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① ui_test.mjs：显示层三条 ───────────────────────────────────────────────
t = io.open(TEST, encoding='utf-8').read()

ANCHOR = '''console.log(`  cell-for-cell     every printed quantity == its observation cell, at 5 moments`);'''

BLOCK = '''// ---------------------------------------------------------------------------------------------
// §345: display names -- `prettifyId` / `displayName` / the replacement table.
//
// 这一层是**纯函数**，所以它能在 Node 里被钉住：内核给 id，屏幕上的名字由这里决定
// （规避版权等用途正是靠那张表）。三条：美化规则、优先级、替换表真的能覆盖内核名。
// ---------------------------------------------------------------------------------------------
{
  const cases = [
    ["entropic_brew", "Entropic Brew"],
    ["acid_slime_m", "Acid Slime M"],
    ["defend+", "Defend+"],
    ["standard.constricted", "Constricted"],
    ["slime_boss", "Slime Boss"],
    ["", ""],
    [null, ""],
  ];
  for (const [input, want] of cases) {
    const got = UI.prettifyId(input);
    if (got !== want) fail(`prettifyId(${JSON.stringify(input)}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }

  // 优先级：替换表 > 内核名 > 美化 id。
  const plain = UI.displayName("entropic_brew", "");
  if (plain !== "Entropic Brew") fail(`displayName without a kernel name: ${plain}`);
  const withKernel = UI.displayName("entropic_brew", "Entropic Brew (content)");
  if (withKernel !== "Entropic Brew (content)") {
    fail(`the kernel/content name must win over the prettifier: ${withKernel}`);
  }
  // ★ 替换表必须能**覆盖**内核名 —— 否则"屏幕上的名字与内核不同"这件事做不到。
  UI.NAMES["slime_boss"] = "胶质巨像";
  try {
    const replaced = UI.displayName("slime_boss", "Slime Boss");
    if (replaced !== "胶质巨像") {
      fail(`the replacement table must override the kernel name, got ${replaced}`);
    }
  } finally {
    delete UI.NAMES["slime_boss"];
  }
  // 空 id 不编名字（`""` 是"没有"，不是"未命名"）。
  if (UI.displayName("", "Some Name") !== "Some Name") fail("an empty id must fall through");
  if (UI.displayName("", "") !== "") fail("two empties must stay empty");
}

console.log(`  display names     prettifyId rules; table > kernel name > prettified id`);'''

t = sub(t, ANCHOR, BLOCK + '\n' + ANCHOR, 'display name tests')
io.open(TEST, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② rd-wasm：Boss id 按幕不同 ─────────────────────────────────────────────
t = io.open(RUN, encoding='utf-8').read()

ANCHOR2 = '''    /// §344：缺口 G1 / G2 / G9 的三个导出各测一次（值 + 哨兵）。'''

TEST2 = '''    /// §345（缺口 G5）：`rd_run_boss_id_*` 按**幕**给不同的 id。
    ///
    /// 页面前写死了 "Slime Boss" —— 第二、三幕会显示错的 Boss 名。判据要求三幕**互不相同**：
    /// 只断言"非空"的话，一个永远返回第一幕的 Boss 的实现也会绿（那正是写死的等价物）。
    #[test]
    fn the_boss_id_follows_the_act() {
        crate::take_session();
        *run_slot() = None;
        assert_eq!(rd_run_boss_id_len(), -1, "no run at all");

        reset(7);
        let read = || {
            let len = rd_run_boss_id_len();
            assert!(len > 0, "act {} has no boss id", rd_run_act());
            let ptr = std::ptr::addr_of_mut!(RUN_SCRATCH) as *mut u8;
            let written = unsafe { rd_run_boss_id_into(ptr) };
            assert_eq!(written, len);
            let bytes = unsafe { std::slice::from_raw_parts(ptr, len as usize) };
            std::str::from_utf8(bytes).expect("ascii").to_string()
        };

        let act1 = read();
        assert_eq!(act1, "slime_boss", "act 1's boss is the Slime Boss");

        // 换幕：`mark_boss_beaten()` 是**公开**的，而且它做的事就是"这一幕通关了 ⇒ act + 1"
        // （最后一幕除外）。不用真的打三场 Boss 战 —— 这条判据问的是"按幕查池"。
        let mut ids = vec![act1];
        for _ in 2..=3 {
            if let Some(session) = run_slot().as_mut() {
                session.state.mark_boss_beaten();
            }
            ids.push(read());
        }
        assert_ne!(ids[0], ids[1], "act 2 must not show act 1's boss");
        assert_ne!(ids[1], ids[2], "act 3 must not show act 2's boss");
        assert_ne!(ids[0], ids[2], "act 3 must not show act 1's boss");
    }

    /// §344：缺口 G1 / G2 / G9 的三个导出各测一次（值 + 哨兵）。'''

t = sub(t, ANCHOR2, TEST2, 'boss id test')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
print('§345 tests: display layer (ui_test) + boss id (rd-wasm)')
