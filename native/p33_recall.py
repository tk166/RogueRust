"""§383：第四幕没做 ⇒ 篝火不提供 Recall（红钥匙现在是一张白拿的空门票）。

## 玩家问的

"篝火里一开始就有红钥匙，这个似乎不合理和 wiki 对不上？"

## 查证结果：**位置**是对的，缺的是别的东西

两个独立来源都说"任何篝火都能拿"：

* fandom `Keys`：*"The Ruby Key is obtained by taking the Recall action at Rest Sites.
  **The key may be obtained at any Rest Site along the run.**"*
* wiki.gg `Mechanics`：*"Ruby Key: Can be obtained at a Rest Site by clicking the Recall
  action, instead of Smith or Rest (or Lift, Dig and Toke) at the same fire."*

所以"第一幕第一个篝火就能 Recall"**不是** bug。真正缺的是两件：

1. **解锁**：钥匙只在"用 Ironclad / Silent / Defect 各通关一次"之后才出现（wiki `Keys`：
   *"Once the Act 3 Boss has been defeated with all characters except the Watcher at least once
   in a normal run, three keys will begin to appear"*）。我们没有任何元进度，所以"永远已解锁"。
2. **第四幕不存在**：钥匙的唯一用途是进 Act 4。于是现在 Recall 花掉一次篝火机会、拿到一个
   永远用不上的布尔 —— 对玩家来说就是**陷阱选项**。

## 决策

`ACT4_IMPLEMENTED = false`：`campfire_options()` 在它为 false 时**不提供** Recall。
理由与 §259 里 `Peace Pipe` 的判据同一条形状 —— "选项是算出来的，不是记出来的"：
一个当前不可能有用处的选项，比一个不存在的选项更糟（玩家会以为游戏坏了）。

第四幕落地时把它翻成 true，Recall 与红钥匙**不需要任何别的改动**（`rd_run_recall` 一直在）。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. 常量 ────────────────────────────────────────────────────────────────
ANCHOR = '''    #[must_use]
    pub fn campfire_options(&self) -> CampfireOptions {'''
assert t.count(ANCHOR) == 1

BLOCK = '''    /// §383：第四幕（`The Ending`）实现了吗？
    ///
    /// 红钥匙（`Recall`）**唯一**的用途是进 Act 4。第四幕没做的时候提供 Recall 就是给玩家
    /// 一个陷阱：花掉一次篝火机会，换来一个永远用不上的布尔。
    ///
    /// ⚠️ wiki 的**位置**规则是对的（fandom `Keys`：*"The key may be obtained at any Rest Site
    /// along the run"*）—— 所以这不是"改规则"，而是"这个功能现在还不可能有用"。
    /// 第四幕落地时翻成 `true`，Recall 与红钥匙不需要任何别的改动。
    pub const ACT4_IMPLEMENTED: bool = false;

    #[must_use]
    pub fn campfire_options(&self) -> CampfireOptions {'''
t = t.replace(ANCHOR, BLOCK)

# ── 2. 判据 ────────────────────────────────────────────────────────────────
OLD = '''            // §259：红钥匙一局只有一把；拿到之后 Recall 就没了（wiki："if you have not already
            // obtained the Ruby Key this act"）。
            recall: !self.ruby_key,'''
NEW = '''            // §259：红钥匙一局只有一把；拿到之后 Recall 就没了（wiki："if you have not already
            // obtained the Ruby Key this act"）。
            //
            // §383：**第四幕没做 ⇒ 不提供**。wiki 的位置规则（任何篝火）没变，变的是
            // "这个选项现在有没有用处"：钥匙只开 Act 4 的门，而 Act 4 不存在。
            // 这条与 `Peace Pipe` 的"空牌组不给 Toke"是同一个形状：选项是**算**出来的。
            recall: Self::ACT4_IMPLEMENTED && !self.ruby_key,'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 3. 测试：把"默认有 Recall"改成"跟着常量走"，并说明为什么 ────────────────
OLD2 = '''        let base = run.campfire_options();
        assert!(base.rest && base.smith && base.recall, "defaults: Rest / Smith / Recall");'''
NEW2 = '''        let base = run.campfire_options();
        assert!(base.rest && base.smith, "defaults: Rest / Smith");
        // §383：Recall 跟着 `ACT4_IMPLEMENTED` 走。写成"等于常量的否定"而不是写死 `false`：
        // 第四幕落地翻常量时，这条断言**自动**继续守"没有钥匙就不能 Recall"那一半。
        assert_eq!(
            base.recall,
            RunState::ACT4_IMPLEMENTED,
            "Recall is offered exactly when Act 4 can be entered"
        );'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: ACT4_IMPLEMENTED + campfire recall 判据 + 测试')
