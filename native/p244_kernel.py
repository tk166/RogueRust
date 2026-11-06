"""§244 内核：`ChoiceSource::DrawPile`（Secret Technique / Secret Weapon）。

与 §238 的 `ExhaustPile` 完全同形。为什么它值得单独一节：这两张牌的问题语义是
"从**抽牌堆**里挑一张（按 tag 收窄）拿进手牌"，而 `chooseCards` 的候选来源原先只有
手牌/弃牌堆/三条候选。页面不用改 —— ABI 那格照旧是 1（"从牌区选"），来源牌区由 zone id 报给页面。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


patch('state.rs', [
    ('''    /// §238：**消耗堆**（Exhume「把消耗堆里一张拿回手牌」）。
    ExhaustPile,''',
     '''    /// §238：**消耗堆**（Exhume「把消耗堆里一张拿回手牌」）。
    ExhaustPile,
    /// §244：**抽牌堆**（Secret Technique / Secret Weapon「从抽牌堆里挑一张」）。
    ///
    /// 与 `Hand` / `DiscardPile` 的区别只在于"候选人看得见什么"：抽牌堆的顺序对玩家是已知的
    /// （牌堆是公开信息），所以这里**不需要**打乱候选。
    DrawPile,'''),
    ('''            Self::ExhaustPile => Some(CardZone::ExhaustPile),''',
     '''            Self::ExhaustPile => Some(CardZone::ExhaustPile),
            Self::DrawPile => Some(CardZone::DrawPile),'''),
])

patch('exec.rs', [
    ('''        CardZone::ExhaustPile => crate::state::ChoiceSource::ExhaustPile,''',
     '''        CardZone::ExhaustPile => crate::state::ChoiceSource::ExhaustPile,
        // §244：Secret Technique / Secret Weapon —— 从抽牌堆里挑一张。
        CardZone::DrawPile => crate::state::ChoiceSource::DrawPile,'''),
])

patch('rd-wasm/src/lib.rs', [
    ('''            | rd_core::state::ChoiceSource::ExhaustPile => 1,''',
     '''            | rd_core::state::ChoiceSource::ExhaustPile
            // §244: `DrawPile` 同样是"从牌区里选"（Secret Technique / Secret Weapon）。
            | rd_core::state::ChoiceSource::DrawPile => 1,'''),
])
print('done')
