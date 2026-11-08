"""§304 基建：`ChoiceThen::ToHandPrinted` —— "搬进手牌，**价格不动**"。

`gambling_chip` 用现成的 `DiscardThenDraw`（Gambler's Brew 那条），`toolbox` 需要"三选一拿进
手牌、**按它的印刷价格**"。今天最接近的是 `ToHand`，但它的含义是"拿进手牌 + 写一个每副本
价格"——页面那句 `2:3` 的文案写死了"（它这次免费）"。

如果 `toolbox` 复用 `ToHand` 再传 `delta = 0`，行为是对的、**文案是谎**：屏幕上会说它免费，
而内核按印刷价收费。而这正是 §250 反过来那条判据的镜像（"静默忽略一个折扣会让'它免费'变成
一句谎"）。

所以加一个变体：`ToHandPrinted`。它的语义只有一句"搬过去"，并且**拒绝**任何非零 `delta`
（"价格不动"由内核守着，而不是靠调用方记得传 0）。

顺手修一处真错：`rd_env_choice_confirm` 的 `Offered` 分支**无条件**算 `priced_delta`。对
`PlayChosen`（Wish）这类不写价格的变体，那只是靠"恰好 0"没事 —— 而 X 费牌会算出 `Err`，
于是"选它就被拒"。改成"只有真的写价格的变体才算差价"。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
LIB = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
WEB = 'D:/Vibe/sts-tui/web/index.html'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① 变体
    patch(STATE, '''    /// **原地升级**选中的牌（§227，Armaments）：定义 id 变成 `<id>+`，牌**不动**。''',
                '''    /// §304：**搬进手牌，价格一点不动**（`toolbox` 的三选一）。
    ///
    /// 与 [`Self::ToHand`] 的差别只有价格那一半，但那一半必须由**变体**表达：`ToHand` 承诺
    /// "调用方会给一个每副本价格"，页面的文案也是从它推出来的（`2:3` = "它这次免费"）。
    /// 让 `toolbox` 复用 `ToHand` 再传 0，行为对、**话是谎** —— 而屏幕说"免费"、内核收印刷价
    /// 正是 §250 那条判据的镜像。
    ///
    /// `resolve_choice` 对任何非零 `cost_delta` 报 [`ChoiceError::DeltaNotApplicable`]：
    /// "价格不动"是变体的一部分，不是调用方要记得的事。
    ToHandPrinted,
    /// **原地升级**选中的牌（§227，Armaments）：定义 id 变成 `<id>+`，牌**不动**。''')

    # ── ② destination
    patch(STATE, '''            Self::ToHand => CardZone::Hand,
            // 副本落在 `into`（**原件不搬**）；这个返回值的用途是给容量判据当"新卡落在哪儿"。''',
                '''            Self::ToHand => CardZone::Hand,
            // §304：搬进手牌，不写价格。
            Self::ToHandPrinted => CardZone::Hand,
            // 副本落在 `into`（**原件不搬**）；这个返回值的用途是给容量判据当"新卡落在哪儿"。''')

    # ── ③ 落区/价格那几个 match：编译不过就补（先按已知位置改）
    patch(STATE, '''        let writes_a_price = matches!(
            choice.then,
            ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree
        ) || (choice.then == ChoiceThen::ToHand && cost_delta != 0);''',
                '''        let writes_a_price = matches!(
            choice.then,
            ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree
        ) || (choice.then == ChoiceThen::ToHand && cost_delta != 0);
        // §304：`ToHandPrinted` 刻意**不**在这里 —— 它一个字都不写（价格不动）。''')

    # ── ④ wasm：kind 10
    patch(LIB, '''            ChoiceThen::PlayChosen => 9,''',
                '''            ChoiceThen::PlayChosen => 9,
            // §304: `toolbox` —— "take it into your hand at its **printed** price". A new number
            // because the page must not reuse `2:3`, whose sentence promises "免费".
            ChoiceThen::ToHandPrinted => 10,''')

    # ── ⑤ wasm：Offered 分支只在**真的写价格**时算差价
    patch(LIB, '''        let mut total = 0i32;
        for index in &indices {
            let Some(definition) = offered.get(*index) else {
                return refuse_with_text(&std::format!("候选 {index} 不存在"));
            };
            match priced_delta(session, definition.as_str()) {
                Ok(delta) => total = total.saturating_add(delta),
                Err(message) => return refuse_with_text(&message),
            }
        }''',
                '''        // §304：只有**写价格**的变体才算差价。`PlayChosen`（Wish）/`ToHandPrinted`（toolbox）
        // 不写价格，而"顺手算一下"会让 X 费牌在这里被拒（`priced_delta` 对它说不出口），
        // 于是"选它就被拒绝"—— 那不是规则，是这一行多算了一次。
        let takes_a_price = matches!(
            choice.then,
            ChoiceThen::ToHand | ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree
        );
        let mut total = 0i32;
        if takes_a_price {
            for index in &indices {
                let Some(definition) = offered.get(*index) else {
                    return refuse_with_text(&std::format!("候选 {index} 不存在"));
                };
                match priced_delta(session, definition.as_str()) {
                    Ok(delta) => total = total.saturating_add(delta),
                    Err(message) => return refuse_with_text(&message),
                }
            }
        }''')

    # ── ⑥ 页面文案：`2:10`
    patch(WEB, '''    "2:9": "从三张里选一张，**立刻打出**它",''',
               '''    "2:9": "从三张里选一张，**立刻打出**它",
    // §304: `toolbox` -- 与 `2:3` 的区别就是**不免费**，所以句子必须说清楚。
    "2:10": "从三张无色牌里选一张加进手牌（按它的印刷价格）",''')
    print('kernel + page wired')


main()
