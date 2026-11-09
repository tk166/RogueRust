"""§311 负控：把起始状态改回 **plain** id，`three_byrds_each_start_with_their_own_flying` 必须红。

这是这一节唯一有意义的反证：那条判据的立场就是"每只各 3 层"，而旧实现是"一只 9 层"。
制造那一种错，判据必须当场抓住。
"""
import io
import subprocess
import sys

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'

OLD = '''        let unique = unique_instance_id(id, &mut seen);
        let Ok(target) = rd_core::state::CombatantId::new(unique) else {
            return Err(format!("`{unique}` is not a usable combatant id"));
        };'''
NEW = '''        let Ok(target) = rd_core::state::CombatantId::new(id) else {
            return Err(format!("`{id}` is not a usable combatant id"));
        };'''


def main():
    original = io.open(PATH, encoding='utf-8').read()
    assert original.count(OLD) == 1
    try:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(original.replace(OLD, NEW, 1))
        out = subprocess.run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST,
                              '--release', '--', '--test-threads=1', 'three_byrds'],
                             capture_output=True, text=True, errors='replace')
        blob = (out.stdout or '') + (out.stderr or '')
        red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
        print('起始状态改回 plain id -> %s' % ('RED (good)' if red else 'STILL GREEN (bad!)'))
        if not red:
            print(blob[-900:])
            sys.exit(1)
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(original)
    print('负控完成：1/1 按预期变红')


main()
