"""§300：修 `mummified_hand` 的判据 —— 手牌里必须**先有别的牌**。

第一版只把要打的那张放进手牌 ⇒ 打出之后手牌空了 ⇒ "随机一张变 0 费"无事可做，
判据红。红得对：**驱动形状**错了，原子本身没问题（诊断里 `defend` 被正确标成 0 费）。
"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

# 1) 删掉诊断测试
# 2) 在 `play` 闭包里先放三张手牌（不含被打的那张）
OLD = '''            give(&mut state, "hero", status("st_mh", "standard.mummified_hand", 1));
            let card = card_in_hand(&mut state, &content, "hero", card_id);'''
NEW = '''            give(&mut state, "hero", status("st_mh", "standard.mummified_hand", 1));
            // ⚠️ **先铺手牌**：只放"要打的那一张"的话，打出之后手牌是空的 —— 而
            // `mummified_hand` 的"随机一张手牌变 0 费"就没有对象（判据第一版就是这么红的）。
            for filler in ["strike", "defend"] {
                let _ = card_in_hand(&mut state, &content, "hero", filler);
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    # 删诊断
    start = s.index('    #[test]\n    fn zzz_debug_mummified_hand')
    end = s.rstrip('\n').rfind('\n}')
    s = s[:start] + s[end:]
    assert 'zzz_debug' not in s
    assert s.count(OLD) == 1, s.count(OLD)
    s = s.replace(OLD, NEW)
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s)
    print('test drive fixed, diagnostic removed')


main()
