"""§305 `frozen_eye`：**只改视图**的遗物。

wiki（两处独立来源一致）：*"When viewing your Draw Pile, the cards are now shown **in order**."*
Shop 稀有度。

## 它为什么需要"内核里的一条规则"

页面早就有抽牌堆查看器（`drawBtn` → `pileEntries(0)`），而它今天**永远**按 `DrawPile` 的顺序
列出 —— 等于这件遗物一直开着。"没有它"的样子不是"看不到牌"，而是**看到有哪些牌、看不出顺序**
（StS 的抽牌堆面板本来就是这样：那张面板是公开信息，顺序才是秘密）。

所以这一轮的规则只有一句：**没有 `frozen_eye` 时，抽牌堆视图按 id 排序**（确定性、不泄露顺序）。

## 三个落点

1. `RelicEffect::FrozenEye`（**新变体**，不是 `Nothing`）：`Nothing` 的语义是"这件遗物什么也
   不做"，而这件有明确的一件事 —— 只是它发生在**视图**里。用独立变体，`rd_env_frozen_eye`
   才能问"这个变体在不在"，而不是再抄一遍遗物 id。
2. `rd_env_frozen_eye()`：与 `rd_run_wing_boots` 同一个理由单独导出（观察向量是冻结的 ABI）。
3. 页面：`pileEntries(0)` 在 `!frozen_eye` 时排序，并**说明**它是排序的
   （否则"顺序看起来是真的"这件事本身就是误导）。
"""
import io
import json

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
SMOKE = 'D:/Vibe/sts-tui/web/smoke.mjs'
WEB = 'D:/Vibe/sts-tui/web/index.html'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① 变体
    patch(STATE, '''    /// §304：`gambling_chip` —— 开战那一刻问"弃任意张手牌，然后抽同样多张"。''',
                '''    /// §305：`frozen_eye` —— "When viewing your Draw Pile, the cards are now shown **in order**."
    ///
    /// 独立的变体而不是 [`Self::Nothing`]：`Nothing` 的意思是"这件遗物什么也不做"，而这件有
    /// 明确的一件事 —— 只是它发生在**视图**里。有了这个变体，`rd_env_frozen_eye` 问的是
    /// "这个变体在不在"，而不是再抄一遍遗物 id（抄第二份就会漂）。
    FrozenEye,
    /// §304：`gambling_chip` —— 开战那一刻问"弃任意张手牌，然后抽同样多张"。''')

    # ── ② 表项
    patch(STATE, '''            // §304：两件"开战问一句"的遗物（问句在 `rd-wasm` 发起，内核只认形态）。''',
                '''            // §305：`frozen_eye` —— 规则全在视图里（页面读 `rd_env_frozen_eye`）。
            "frozen_eye" => Some(RelicEffect::FrozenEye),
            // §304：两件"开战问一句"的遗物（问句在 `rd-wasm` 发起，内核只认形态）。''')

    # ── ③ 访问器（放在 combat_open_choices 之前）
    patch(STATE, '''    /// §304：这一场开战时要问玩家哪些话 —— 位掩码''',
                '''    /// §305：`frozen_eye` —— 抽牌堆视图要不要**按真实顺序**显示。
    ///
    /// 没有它就返回 `false`：那时视图按 id 排序（"有哪些牌"是公开信息，"顺序"不是）。
    #[must_use]
    pub fn shows_draw_order(&self) -> bool {
        matches!(
            self.first_relic_effect_of(RelicEffect::FrozenEye),
            Some(RelicEffect::FrozenEye)
        )
    }

    /// §304：这一场开战时要问玩家哪些话 —— 位掩码''')

    # ── ④ 三处 match 清单
    patch(STATE, '''            // §304：两件"开战问一句"的遗物也都不在"拿到那一刻"里。
            | RelicEffect::CombatOpenDiscardThenDraw
            | RelicEffect::CombatOpenOfferColorless { .. }''',
                '''            // §304：两件"开战问一句"的遗物也都不在"拿到那一刻"里。
            | RelicEffect::CombatOpenDiscardThenDraw
            | RelicEffect::CombatOpenOfferColorless { .. }
            // §305：`frozen_eye` 只改视图，两个钩子都不参与。
            | RelicEffect::FrozenEye''')

    s = io.open(STATE, encoding='utf-8').read()
    lines = s.split('\n')
    targets = [i for i, line in enumerate(lines)
               if line.strip() == '| RelicEffect::CombatOpenOfferColorless { .. },']
    assert len(targets) == 2, len(targets)
    for i in reversed(targets):
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = lines[i].rstrip()[:-1]
        lines[i + 1:i + 1] = [f'{indent}// §305：`frozen_eye` 只改视图。',
                             f'{indent}| RelicEffect::FrozenEye,']
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))

    # end_of_combat 那份（裸清单）也要补 —— 编译器会指出具体位置
    t = io.open(STATE, encoding='utf-8').read()
    if t.count('| RelicEffect::FrozenEye') < 4:
        anchor = '''                    | RelicEffect::CombatOpenOfferColorless { .. }
                    | RelicEffect::RestCardReward,'''
        if t.count(anchor) == 1:
            t = t.replace(anchor, '''                    | RelicEffect::CombatOpenOfferColorless { .. }
                    | RelicEffect::FrozenEye
                    | RelicEffect::RestCardReward,''')
            io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)

    # ── ⑤ wasm 导出
    patch(RUN, '''/// §303：`wing_boots` 还能飞几次（0..=3）。没有局 ⇒ `-1`，没有遗物 ⇒ `0`。''',
                '''/// §305：`frozen_eye` —— 抽牌堆视图要不要按**真实顺序**显示（`1` 要，`0` 排序显示）。
///
/// 没有局 ⇒ `0`：`rd_env` 的单场战斗没有遗物，所以它的抽牌堆视图就是"排序"的那一版
/// （与"没有这件遗物"逐字同形 —— 这正是它该有的样子）。
#[no_mangle]
pub extern "C" fn rd_env_frozen_eye() -> i32 {
    match run_slot().as_ref() {
        Some(session) if session.state.shows_draw_order() => 1,
        _ => 0,
    }
}

/// §303：`wing_boots` 还能飞几次（0..=3）。没有局 ⇒ `-1`，没有遗物 ⇒ `0`。''')

    # ── ⑥ smoke 的导出对账
    patch(SMOKE, '''  "rd_run_wing_boots",''', '''  "rd_run_wing_boots",
  "rd_env_frozen_eye",''')

    # ── ⑦ 页面：抽牌堆视图
    patch(WEB, '''function pileEntries(zone) {
  const out = [];
  for (let index = 0; index < ex.rd_env_pile_len(zone); index++) {
    out.push(`<div class="card">${esc(pileTitle(zone, index))}</div>`);
  }
  return out;
}''', '''// §305: the draw pile is a **view**, and `frozen_eye` decides which one.
//
// Without the relic the panel still shows *which* cards are in the pile (that is public
// information) but not the **order** they will come back in -- so the list is sorted by id, which
// is deterministic and leaks nothing. With the relic it is the kernel's own order (`index` into
// `DrawPile`). One reader, two views, and the hint says which one you are looking at: a list that
// merely *looks* authoritative is the worse failure.
function pileEntries(zone) {
  const out = [];
  const count = Math.max(0, ex.rd_env_pile_len(zone));
  const entries = [];
  for (let index = 0; index < count; index++) {
    entries.push({ index, title: pileTitle(zone, index), id: pileId(zone, index) });
  }
  if (zone === 0 && ex.rd_env_frozen_eye() !== 1 && entries.length > 1) {
    entries.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    out.push(`<div class="dim">没有 <b>Frozen Eye</b>：这里只显示**有哪些**牌，顺序按名称排序</div>`);
  }
  for (const entry of entries) {
    out.push(`<div class="card">${esc(entry.title)}</div>`);
  }
  return out;
}''')

    # ── ⑧ 内容遗物行
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    if not any(r['Id'] == 'frozen_eye' for r in doc['Relics']):
        doc['Relics'].append({'Id': 'frozen_eye', 'DisplayName': 'Frozen Eye',
                              'RunPrograms': None, 'CombatRules': None, 'Rarity': 'Shop'})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

    c = io.open(CHECK, encoding='utf-8').read()
    old = '''                      # §304：两件"开战问一句"的遗物。
                      "gambling_chip", "toolbox",'''
    assert c.count(old) == 1
    c = c.replace(old, '''                      # §304：两件"开战问一句"的遗物。
                      "gambling_chip", "toolbox",
                      # §305：`frozen_eye`（只改视图）。
                      "frozen_eye",''')
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(c)
    print('frozen_eye wired; relics =', len(doc['Relics']))


main()
