"""§313（六·修）：第三段判据的计数器写入写错了。

`for (name, value) in (("prev_move", 3), ("last_move", 3))` —— 那是**元组**不是数组（不可迭代），
而且我顺手留了一句 `Ident::<32>` 的无用代码。改成 `[("prev_move", 3), ("last_move", 3)]` +
`set_counter(CounterId, i32)`（`state.rs:1481` 的签名）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

OLD = '''        {
            let session = slot().as_mut().expect("session");
            let combatant = session.state.combatant_mut(&cid_in("mystic")).expect("mystic");
            for (name, value) in (("prev_move", 3), ("last_move", 3)) {
                let key = rd_core::state::Ident::<32>::new(name).expect("counter id");
                combatant
                    .set_counter(rd_core::state::CounterId::new(name).expect("id"), value)
                    .ok();
                let _ = key;
            }
        }'''

NEW = '''        {
            let session = slot().as_mut().expect("session");
            let combatant = session.state.combatant_mut(&cid_in("mystic")).expect("mystic");
            for (name, value) in [("prev_move", 3), ("last_move", 3)] {
                combatant
                    .set_counter(rd_core::state::CounterId::new(name).expect("counter id"), value)
                    .expect("room for two counters");
            }
        }'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(OLD) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(OLD, NEW))
    print('counter block fixed')


main()
