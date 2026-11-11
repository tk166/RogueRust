"""port-plan §352：P1-A / P1-B 两个纯状态机缺陷的修复与守卫。"""

import io

PATH = 'docs/port-plan.md'
t = io.open(PATH, encoding='utf-8').read()
anchor = '''### 残留

- 真机性能没测（headless 软件光栅的 60 fps 什么都不能说明）；'''
assert t.count(anchor) == 1, '锚点命中 %d 次' % t.count(anchor)

addition = '''---

## §352 P1-A / P1-B：两个"41 条断言都看不见"的状态机缺陷

第十三轮 Review 指出两条功能缺陷，并注明是"按控制流推导、未独立复现"。**两条都复现了**
（`native/p1_review13_repro.mjs` 把 `pointerMachine.ts` 编成 JS 再跑，不是静态推断）。

### P1-A：同一动作做两次，第二次被内容去重吞掉

`App.tsx` 用 `JSON.stringify(lastResult)` 当事件身份。但"同一张牌打同一个敌人两次"的 payload
**完全相同**，于是第二次被当成重复事件。P1 Mock 手牌不移除，直接可构造；接真实 WASM 后，
下一回合同一槽位抽到同名牌同样是合法局面 —— 不是假想。

修法：`State.resultSeq` 单调递增（`finish` / `cancel` 各 +1，`down` **保留**），App 按序号去重。
**事件身份是"第几次发生"，不是"内容长什么样"。**

### P1-B：无目标牌丢在敌人身上，判定与执行互相矛盾

`decide()` 对无目标牌返回 `commit`（丢哪儿都算数），`finish()` 却拿**物理落点** `targetSlot`
去 `options.find()`；无目标牌只有 `slot === -1` 一项 ⇒ 丢在敌人 `slot=1` 上查不到 ⇒ 变成
`rebound`。

修法：**物理命中位置与业务动作目标分开** —— 无目标牌一律取 `slot === -1`，提交写
`targetSlot: chosen.slot`。

### 为什么 41 条浏览器断言全都没抓到

它们没有一条要求**同一件事做两次**。我的四次提交恰好是四张不同的牌、三个不同的目标。
这不是"想错了"，是"断言里没有这个形状"。

### 守卫

- **闸门 25 `ui-next`** 加两个场景：同一动作两次（`commits` 2→3、敌人 44→38→32）、
  无目标牌丢在敌人身上（提交且 `targetSlot === -1`，并且**真的**又加了 5 点格挡）。
  计数改成"做之前捕获 + N"的相对写法 —— 绝对数字每加一个场景就要改五处，那是漂移的温床。
- **新闸门 26 `ui-pointer`**：纯状态机回归（不需要浏览器）。与闸门 25 分开的理由是
  "红了能一眼看出坏在状态机、接线还是渲染"。
- **负控**：把两个修复回退后重跑闸门 25 ⇒ **6 条红**（正是那两个缺陷）；恢复 ⇒ 全绿。

### 两个"守卫自己没牙"的坑（都踩了）

1. 复现脚本第一版断言"两次 payload 不同"——**错**。修法不是让 payload 不同（动作本来就一样），
   而是让**事件序号**不同。断言测错了性质，改完仍红。
2. 复现脚本第一版每次从 `INITIAL` 重来 ⇒ `resultSeq` 永远是 1，"序号递增"测的是脚本自己的 bug。
   必须沿同一条状态链走（真实 store 是长活的）。
3. 闸门 26 第一次接进验收就红：`Invoke-Gate` 给的是**收窄的 PATH**（只有 cargo / System32 /
   dotnet），`npx` 不在里面。改成用 `process.execPath` 直接跑 `typescript/bin/tsc.js`，与 PATH 无关。

### 数字

闸门 25 → **26**；`ui-next` 证据 `commits=4` → **`commits=6`**；units 1233、导出 234、四条对拍不动。

### 残留

- 真机性能没测（headless 软件光栅的 60 fps 什么都不能说明）；'''

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))
print('port-plan §352 added')
