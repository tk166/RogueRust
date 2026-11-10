"""§331 修：判据用错了镜像。

`tools/contentc/out/content.rdcf` 是 **roguedeck** 包的镜像（没有 `UnknownRooms`，也就没有事件），
而 sts 的镜像是 `tools/contentc/packages/sts/out/content.sts.rdcf`。用错之后第一行就 panic，
报错是 "the act-3 pool" —— 看起来像"池子读不出来"，实际是"这个包里根本没有事件表"。
顺手拆掉定位用的插桩。
"""

import io

PATH = 'kernel/rd-core/src/content.rs'

OLD = """        let blob = std::fs::read(FULL_IMAGE).expect("the full image");
        let content = Content::parse(&blob).expect("parses");
        let base = crate::run_expr::RunFacts {"""

NEW = """        // ⚠️ 用 **sts** 包的镜像：`tools/contentc/out/content.rdcf` 是 `roguedeck` 那一份，
        // 它没有 `UnknownRooms`（也就没有事件）—— 拿它跑这条判据会在第一行 panic，
        // 而报错是 "the act-3 pool"，看起来像"池子读不出来"。
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&blob).expect("parses");
        let base = crate::run_expr::RunFacts {"""

INSTRUMENT = [
    ('''            let element = match list.cell(index) { Some(v) => v, None => { std::eprintln!("DEBUG cell {}", index); return None; } };
            let element_term = match self.term(element) { Some(v) => v, None => { std::eprintln!("DEBUG term {}", index); return None; } };''',
     '''            let element = list.cell(index)?;
            let element_term = self.term(element)?;'''),
    ('''            if element_term.op < OP_FIRST_DYNAMIC {
                std::eprintln!("DEBUG static op {}", index);
                return None;
            }
            let element_opcode = match self.opcode(element_term.op) { Some(v) => v, None => { std::eprintln!("DEBUG opcode {}", index); return None; } };''',
     '''            if element_term.op < OP_FIRST_DYNAMIC {
                return None;
            }
            let element_opcode = self.opcode(element_term.op)?;'''),
    ('''                match crate::run_expr::option_is_available(self, element, facts) {
                    Ok(true) => {}
                    Ok(false) => continue,
                    Err(e) => { std::eprintln!("DEBUG requires err {:?} id={}", e, id); return None; }
                }''',
     '''                if !crate::run_expr::option_is_available(self, element, facts).ok()? {
                    continue;
                }'''),
]

t = io.open(PATH, encoding='utf-8').read()
assert t.count(OLD) == 1, 'image anchor'
t = t.replace(OLD, NEW)
for old, new in INSTRUMENT:
    assert t.count(old) == 1, old[:50]
    t = t.replace(old, new)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('image fixed + instrumentation removed')
