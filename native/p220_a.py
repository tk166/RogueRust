"""§220 patch A: generalize the lifecycle decoder to `Drawn` / `Exhausted`."""
import io

HOST = 'kernel/rd-core/src/host.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(HOST, '''fn card_lifecycle_turn_end_program<'a>(
    content: &'a Content<'a>,
    definition_id: &str,
) -> Result<Option<LifecycleProgram<'a>>, HostError> {
    let row = card_row(content, definition_id).ok_or(HostError::Content("CARD row"))?;
    let handle = row.lifecycle_programs();
    if handle == ABSENT16 || handle == NULL16 {
        // 整格缺席 / 显式 null ⇒ 参考那边是空字典 ⇒ 没有节目。
        return Ok(None);
    }
    let term = content
        .term(handle)
        .ok_or(HostError::Content("LifecyclePrograms"))?;
    if term.op < crate::content::OP_FIRST_DYNAMIC {
        // `_arr`/`_str`/`_int`… 都不是"字典"的编码。
        return Err(HostError::Content("LifecyclePrograms"));
    }
    let opcode = content
        .opcode(term.op)
        .ok_or(HostError::Content("LifecyclePrograms"))?;
    let node = NodeRef::new(content, handle);
    let mut program: Option<NodeRef<'a>> = None;
    for index in 0..opcode.nfields() {
        let field = opcode
            .field(index)
            .ok_or(HostError::Content("LifecyclePrograms"))?;
        let name = content
            .string(field.name_str())
            .ok_or(HostError::Content("LifecyclePrograms"))?;
        if name != TURN_END_IN_HAND && name != TURN_END_IN_HAND_ORDINAL {
            return Err(HostError::Unsupported("CardLifecycleTrigger"));
        }
        if program.is_some() {
            // 两种拼法同时出现 ⇒ 同一个触发器写了两条节目。
            return Err(HostError::Content("LifecyclePrograms"));
        }
        match node.field(name)? {
            // `F_TERM` 的缺席哨兵 ⇒ 这个键没写。
            None | Some(Value::Absent) => {}
            Some(Value::Null) => return Err(HostError::Content("LifecyclePrograms")),
            Some(Value::Node(inner)) => program = Some(inner),
            // 声明成 `F_TERM` 却装了标量：`field()` 已经在这里报过错了，这一支不可达。
            Some(_) => return Err(HostError::Content("LifecyclePrograms")),
        }
    }''',
    '''/// §220：`LifecyclePrograms` 的**键名** → 事件。`None` = 这个键内核不认识（必须响亮）。
///
/// 参考的 `CardLifecycleTrigger` 只有 `TurnEndInHand`（及其枚举序数 `0`）；`Drawn` / `Exhausted`
/// 是**我们自己的扩展**（`void` 的"抽到时 -1 能量"、`sentinel` 的"被消耗时 +2 能量"），
/// 与 §198 的 `Operation::ScalePercentPerStack` 同级。**不认识的键仍然拒绝**：
/// 那是"内容写了本层读不懂的触发器"，不是"没有触发器"。
#[must_use]
pub fn lifecycle_name_matches(name: &str, wanted: Option<crate::state::CardLifecycleEvent>) -> Option<bool> {
    let known: Option<Option<crate::state::CardLifecycleEvent>> = match name {
        TURN_END_IN_HAND | TURN_END_IN_HAND_ORDINAL => Some(None),
        "Drawn" => Some(Some(crate::state::CardLifecycleEvent::Drawn)),
        "Exhausted" => Some(Some(crate::state::CardLifecycleEvent::Exhausted)),
        _ => None,
    };
    known.map(|event| event == wanted)
}

pub(crate) fn card_lifecycle_program<'a>(
    content: &'a Content<'a>,
    definition_id: &str,
    wanted: Option<crate::state::CardLifecycleEvent>,
) -> Result<Option<LifecycleProgram<'a>>, ExecError> {
    let row = card_row(content, definition_id)
        .ok_or(ExecError::Ir(IrError::Missing("CARD row")))?;
    let handle = row.lifecycle_programs();
    if handle == ABSENT16 || handle == NULL16 {
        // 整格缺席 / 显式 null ⇒ 参考那边是空字典 ⇒ 没有节目。
        return Ok(None);
    }
    let term = content
        .term(handle)
        .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
    if term.op < crate::content::OP_FIRST_DYNAMIC {
        // `_arr`/`_str`/`_int`… 都不是"字典"的编码。
        return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms")));
    }
    let opcode = content
        .opcode(term.op)
        .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
    let node = NodeRef::new(content, handle);
    let mut program: Option<NodeRef<'a>> = None;
    for index in 0..opcode.nfields() {
        let field = opcode
            .field(index)
            .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
        let name = content
            .string(field.name_str())
            .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
        // §220：不认识的键仍是 `UnknownKind`（"判别串不认识"），与 `zone_from_wire_name` 同形。
        let matches = lifecycle_name_matches(name, wanted)
            .ok_or(ExecError::Ir(IrError::UnknownKind))?;
        if !matches {
            continue;
        }
        if program.is_some() {
            // 两种拼法同时出现 ⇒ 同一个触发器写了两条节目。
            return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms")));
        }
        match node.field(name)? {
            // `F_TERM` 的缺席哨兵 ⇒ 这个键没写。
            None | Some(Value::Absent) => {}
            Some(Value::Null) => {
                return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms")))
            }
            Some(Value::Node(inner)) => program = Some(inner),
            // 声明成 `F_TERM` 却装了标量：`field()` 已经在这里报过错了，这一支不可达。
            Some(_) => return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms"))),
        }
    }''',
    'decoder')

one(HOST, '''    let root = program
        .node_field("Root")?
        .ok_or(HostError::Content("LifecyclePrograms"))?;
    let max_steps = match program.int_field("MaxProgramSteps")? {
        Some(value) if value > 0 => u32::try_from(value).unwrap_or(DEFAULT_MAX_PROGRAM_STEPS),
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    };
    Ok(Some(LifecycleProgram { root, max_steps }))
}''',
    '''    let root = program
        .node_field("Root")?
        .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
    let max_steps = match program.int_field("MaxProgramSteps")? {
        Some(value) if value > 0 => u32::try_from(value).unwrap_or(DEFAULT_MAX_PROGRAM_STEPS),
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    };
    Ok(Some(LifecycleProgram { root, max_steps }))
}''',
    'decoder tail')

one(HOST, '''struct LifecycleProgram<'a> {''', '''pub(crate) struct LifecycleProgram<'a> {''', 'program visibility')

# 调用点：turn-end 扫描要 `TurnEndInHand`（None），错误用 HostError::Exec 包一层
one(HOST, '''            if let Some(program) = card_lifecycle_turn_end_program(content, definition.as_str())? {''',
    '''            let decoded = card_lifecycle_program(content, definition.as_str(), None)
                .map_err(|error| self.record(HostError::Exec(error)))?;
            if let Some(program) = decoded {''',
    'turn-end call site')

io.open(HOST, 'a', encoding='utf-8', newline='\n').write('')
print('host patched')
