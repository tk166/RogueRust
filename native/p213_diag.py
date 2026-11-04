import io

P = 'kernel/rd-core/src/host.rs'
text = io.open(P, encoding='utf-8').read()

anchor = """    #[test]
    fn regen_heals_at_the_end_of_the_turn() {"""
probe = '''    /// TEMP DIAG (§213): run every content trigger program once and name the ones that fail.
    #[test]
    fn diag_every_trigger_program_runs() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut failures = Vec::new();
        for row in content.rows(crate::content::Table::Status) {
            let id = row.str_field("Id").ok().flatten().unwrap_or("<none>").to_string();
            let mut handles = [0u16; 4];
            let count = match crate::status_bind::trigger_handles(&content, &id, &mut handles) {
                Ok(count) => count,
                Err(e) => {
                    failures.push(std::format!("{id}: handles {e:?}"));
                    continue;
                }
            };
            for index in 0..count {
                let Some(handle) = handles.get(index).copied() else { continue };
                let entry = crate::ir::NodeRef::new(&content, handle);
                let event = entry.str_field("Event").ok().flatten().unwrap_or("?").to_string();
                let Some(program) = entry.node_field("Program").ok().flatten() else {
                    failures.push(std::format!("{id}/{event}: no Program"));
                    continue;
                };
                let root = match program.node_field("Root").ok().flatten() {
                    Some(root) => root,
                    None => {
                        failures.push(std::format!("{id}/{event}: no Root"));
                        continue;
                    }
                };
                let mut state = arena();
                give(&mut state, "hero", status("st_x", &id, 1));
                let mut ctx = crate::exec::ExecContext::new(
                    &mut state, Some(cid("hero")), Some(cid("enemy_a")), None, 1024)
                    .with_content(&content);
                if let Err(error) = crate::exec::begin(root, &mut ctx, crate::state::ProgramTerminalHook::None) {
                    failures.push(std::format!("{id}/{event}: {error:?}"));
                }
            }
        }
        assert!(failures.is_empty(), "{failures:#?}");
    }

''' + anchor
assert text.count(anchor) == 1
io.open(P, 'w', encoding='utf-8', newline='').write(text.replace(anchor, probe, 1))
print("diag test added")
