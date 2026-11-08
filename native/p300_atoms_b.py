"""§300：把 `chooseCards` 的 `then` 查表抽成 `choice_then_from_name`，供两个节点共用。

**一份词表**：`offerRandomCards` 与 `chooseCards` 说的是同一件事（"选完做什么"），
两处各写一个 `match` 就是"同一个词表被两处认识"（§4.20 那类漂移的起点）。
"""
import io

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'


def main():
    s = io.open(EXEC, encoding='utf-8').read()

    # 1) 把 chooseCards 里的那段 match 换成函数调用
    start = s.index('    let then = match then_name {')
    end = s.index('        _ => return Err(ExecError::Ir(IrError::UnknownKind)),\n    };', start)
    end += len('        _ => return Err(ExecError::Ir(IrError::UnknownKind)),\n    };')
    old_block = s[start:end]
    assert 'ToDrawPileTop' in old_block and 'ToHandFree' in old_block
    s = s[:start] + '    let then = choice_then_from_name(then_name, node)?;' + s[end:]

    # 2) 把旧块体改造成函数，挂在 choose_cards_node 之前
    body = old_block.replace('    let then = match then_name {', '    match then_name {')
    body = body.rstrip('\n')
    assert body.endswith('}')
    body = body[:-1] + '}\n'   # 保持一个闭合
    function = '''/// §300：`Then` 的名字 → [`crate::state::ChoiceThen`] 的**唯一**一张表。
///
/// 两个节点共用它：`chooseCards`（问"已有的哪几张"）与 `offerRandomCards`（问"这几张新的
/// 里要哪个"）。§300 之前 `offerRandomCards` 把 `then` **写死**成 `ToHandFree`，于是
/// "三选一，塞进抽牌堆"（`nilrys_codex`）在内容里表达不出来 —— 而词表其实早就有了。
fn choice_then_from_name(
    then_name: &str,
    node: NodeRef<'_>,
) -> Result<crate::state::ChoiceThen, ExecError> {
''' + body.replace('        "Copy" =>', '    "Copy" =>').replace('    let copies', '    let copies') + '''
}

'''

    anchor = 'fn choose_cards_node('
    index = s.index(anchor)
    # 找到 choose_cards_node 的文档注释起点
    doc_start = s.rfind('\n///', 0, index)
    doc_start = s.rfind('\n\n', 0, doc_start) + 1
    s = s[:doc_start] + function + s[doc_start:]

    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(s)
    print('choice_then_from_name extracted')


main()
