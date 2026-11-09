"""§315（三·修）：`lookup_in` 返回 `Option`（不是 `Result`），闭包签名对不上。

顺带把 `encounter_enemies` 的读取写直白：它给的是 `Vec<Result<EnemySpec>>`，
所以 `first()` 得到 `&Result` —— 用 `match` 一次说清"缺了"与"坏了"两种情形。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

OLD = '''            .map(|eid| {
                let index = u32::from(
                    content
                        .lookup_in(eid, rd_core::content::EK_ENCOUNTER)
                        .unwrap_or_else(|e| panic!("{eid}: {e:?}"))
                        .index,
                );
                let enemies = content.encounter_enemies(index).expect("enemies");
                let spec = enemies
                    .iter()
                    .next()
                    .expect("one enemy")
                    .expect("the record");'''

NEW = '''            .map(|eid| {
                let entry = content
                    .lookup_in(eid, rd_core::content::EK_ENCOUNTER)
                    .unwrap_or_else(|| panic!("{eid} is not in the image"));
                let index = u32::from(entry.index);
                let enemies = content.encounter_enemies(index).expect("enemies");
                let spec = match enemies.first() {
                    Some(Ok(spec)) => *spec,
                    Some(Err(error)) => panic!("{eid}: first enemy record is invalid: {error:?}"),
                    None => panic!("{eid} has no enemies"),
                };'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(OLD) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(OLD, NEW))
    print('test fixed')


main()
