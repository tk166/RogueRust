"""闸门 25 补两条（第十三轮 Review 的 P1-A / P1-B），并把绝对计数改成相对计数。

## 为什么必须进闸门

这两条都是**从控制流能推出来、但 41 条断言全都没覆盖**的缺陷 —— 我的四次提交恰好都是
不同的牌与目标。缺陷不在"想错了"，而在"没有一条断言要求同一件事做两次"。

## 断言写法

计数一律用"做之前捕获、做之后 +N"，不用绝对值：这样后面再加场景不会连带改一串数字
（第一版全是绝对值，加一条就要改五处 —— 那正是"数字漂移"的温床）。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# ── 场景 1：改成相对计数 + 新增 1b「同一动作连做两次」──────────────────────
sub(
    '''let commits = await evaluate("window.__p1.commits()");
check(commits.length === 1, "拖动并释放后恰好 1 次提交", `got ${commits.length}`);
check(commits[0]?.targetSlot === 1, "打的是**敌人 1**（不是就近的那个）", JSON.stringify(commits[0]));
check(commits[0]?.card === "strike", "打的是 strike", JSON.stringify(commits[0]));
const afterStrike = await evaluate("window.__p1.enemies()");
check(afterStrike[1].hp === 38 && afterStrike[0].hp === 32, "只有敌人 1 掉血（44 → 38）", JSON.stringify(afterStrike));''',
    '''let commits = await evaluate("window.__p1.commits()");
check(commits.length === 1, "拖动并释放后恰好 1 次提交", `got ${commits.length}`);
check(commits[0]?.targetSlot === 1, "打的是**敌人 1**（不是就近的那个）", JSON.stringify(commits[0]));
check(commits[0]?.card === "strike", "打的是 strike", JSON.stringify(commits[0]));
const afterStrike = await evaluate("window.__p1.enemies()");
check(afterStrike[1].hp === 38 && afterStrike[0].hp === 32, "只有敌人 1 掉血（44 → 38）", JSON.stringify(afterStrike));

// ── 1b. 同一张牌打同一个敌人**两次**（§352 P1-A）──────────────────────────
// payload 完全相同，所以"按内容去重"会把第二次吞掉。事件身份必须是**第几次发生**。
const grabbedAgain = await mouseDrag(strikeAt, enemy1At);
check(
  grabbedAgain.phase === "pressed" && grabbedAgain.handSlot === 0,
  "第二次按下仍命中的是第 0 张牌",
  JSON.stringify(grabbedAgain)
);
commits = await evaluate("window.__p1.commits()");
check(commits.length === 2, "同样的动作做两次 ⇒ 两次提交（不被内容去重吞掉）", `commits=${commits.length}`);
const afterRepeat = await evaluate("window.__p1.enemies()");
check(afterRepeat[1].hp === 32, "敌人 1 掉了两次血（44 → 38 → 32）", JSON.stringify(afterRepeat));''',
    'scenario 1b',
)

# ── 场景 2（非法释放）：相对计数 ────────────────────────────────────────────
sub(
    '''commits = await evaluate("window.__p1.commits()");
const rebounds = await evaluate("window.__p1.rebounds()");
check(commits.length === 1, "非法释放没有产生提交", `commits=${commits.length}`);''',
    '''commits = await evaluate("window.__p1.commits()");
const rebounds = await evaluate("window.__p1.rebounds()");
check(commits.length === 2, "非法释放没有产生提交", `commits=${commits.length}`);''',
    'scenario 2 count',
)

# ── 场景 3（无目标牌 → 空白）：相对计数 + 新增 3b（无目标牌 → 敌人）────────
sub(
    '''commits = await evaluate("window.__p1.commits()");
check(commits.length === 2, "无目标牌在空白处释放也提交", `commits=${commits.length}`);
check(commits[1]?.targetSlot === -1, "无目标牌的 targetSlot 是 -1", JSON.stringify(commits[1]));
const blockAfter = (await evaluate("window.__p1.hero()")).block;
check(blockAfter === blockBefore + 5, "防御牌真的加了 5 点格挡", `${blockBefore} -> ${blockAfter}`);''',
    '''commits = await evaluate("window.__p1.commits()");
check(commits.length === 3, "无目标牌在空白处释放也提交", `commits=${commits.length}`);
check(commits.at(-1)?.targetSlot === -1, "无目标牌的 targetSlot 是 -1", JSON.stringify(commits.at(-1)));
const blockAfter = (await evaluate("window.__p1.hero()")).block;
check(blockAfter === blockBefore + 5, "防御牌真的加了 5 点格挡", `${blockBefore} -> ${blockAfter}`);

// ── 3b. 无目标牌释放在**敌人身上**（§352 P1-B）────────────────────────────
// 物理落点是敌人 0，但业务目标永远是 -1。旧实现拿物理落点去查选项 ⇒ 查不到 ⇒ 误回弹，
// 而 `decide()` 判的是 commit —— 判定与执行互相矛盾。
const enemy0At = await enemyPoint(0);
const beforeUntargetedOnEnemy = await evaluate("window.__p1.hero()");
const grabbedOnEnemy = await mouseDrag(defendAt, enemy0At);
check(
  grabbedOnEnemy.phase === "pressed" && grabbedOnEnemy.handSlot === 1,
  "第三次按下仍命中的是第 1 张牌（防御）",
  JSON.stringify(grabbedOnEnemy)
);
commits = await evaluate("window.__p1.commits()");
check(commits.length === 4, "无目标牌丢在敌人身上也提交（不误判回弹）", `commits=${commits.length}`);
check(
  commits.at(-1)?.targetSlot === -1,
  "无目标牌丢在敌人身上，业务目标仍是 -1",
  JSON.stringify(commits.at(-1))
);
const afterUntargetedOnEnemy = await evaluate("window.__p1.hero()");
check(
  afterUntargetedOnEnemy.block === beforeUntargetedOnEnemy.block + 5,
  "这一次也真的加了 5 点格挡（不是只记了一笔提交）",
  `${beforeUntargetedOnEnemy.block} -> ${afterUntargetedOnEnemy.block}`
);''',
    'scenario 3b',
)

# ── 场景 5 里 `enemy0At` 会重复声明 ────────────────────────────────────────
sub(
    '''const twinAt = await cardPoint(6);
const enemy0At = await enemyPoint(0);
const beforeTouch = (await evaluate("window.__p1.commits()")).length;''',
    '''const twinAt = await cardPoint(6);
const beforeTouch = (await evaluate("window.__p1.commits()")).length;''',
    'dedupe enemy0At',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate 25: P1-A / P1-B scenarios added')
