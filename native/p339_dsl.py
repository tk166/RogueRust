"""§339：条件 DSL 补上 **OR**（`RequiresAny`），并修掉两处词表漂移。

## 为什么要 OR

八轮 Review 2.2：`The Moai Head` 的出现条件是 **"有 Golden Idol **或** HP ≤ 50%"**
（wiki 原文 "either has Golden Idol, **or** their HP is at or below 50%"）。而
`rd-core::run_expr` 的形态是"一串原子、全部成立才成立（AND）"，`Requires` 里写两条
只会变成"两个都满足" —— 于是满血 + 持有 Golden Idol 的玩家永远遇不到这个事件。

模块头自己写着"缺 `or` 是**已知的表达力缺口**，真出现时再加" —— 现在真出现了。

## 为什么是第二个**平铺**列表，不是布尔树

一棵树要一套解析器、一套求值器、一套"这张表里有但没实现"的判据；而真实内容里的需求只有
"AND 一组、OR 一组"这一种形状。所以：

    AND(Requires) && ( RequiresAny 为空 || OR(RequiresAny) )

**组内 OR、组间 AND**，两组都是同一串原子（同一个 `atom_holds`），容量也共用
`MAX_REQUIREMENTS`。树留到真的需要嵌套时再说 —— 那时它值单独一节。

⚠️ 不做 `RequiresAnyAsc`：Moai 的条件与 Ascension 无关。`RequiresAsc` 之所以存在，是因为
A15 真的改了价目（`The Cleric` 的 Purify 50 → 75）。"以后可能需要"不是加接口的理由。

## 两处词表漂移（`FACT.md` §4.20 的同一个形状）

`native/sts_content_check.py` 里有一份**手抄的** `REQUIRES_KINDS`，注释写着"必须与
`rd-core::run_expr` 一致"，而 §331 加 `relic_count` 时**只改了 Rust 那一份**。
现在两处都会认 `relic_count`，并且内容门**也开始检查事件级的 `Requires` / `RequiresAny`**
（原来只查选项级，所以漂了也没人红）。
"""

import io

PATH = 'kernel/rd-core/src/run_expr.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── ① 模块头：把"已知缺口"改成"已补，并说明形状" ─────────────────────────────
OLD_HEAD = '''//! 缺 `or` 是**已知的表达力缺口**，不是遗漏：真出现"要么有 X 要么有 Y"的选项时再加一棵树，
//! 那时它值一次单独一节（与 §278 的 `EVND` 同一档）。'''

NEW_HEAD = '''//! # §339：`RequiresAny` —— 组内 OR、组间 AND
//!
//! ```json
//! "RequiresAny": [
//!   {"Kind": "health_percent", "Op": "at_most", "Amount": 50},
//!   {"Kind": "relic", "Op": "has", "Id": "golden_idol"}
//! ]
//! ```
//!
//! 语义是 `AND(Requires) && (RequiresAny 为空 || OR(RequiresAny))`。它存在的理由是一个
//! **真实的内容缺口**：`The Moai Head` 的出现条件是 "either has Golden Idol, **or** their HP
//! is at or below 50%"（wiki），而一串 AND 原子表达不了 —— 写两条会变成"两个都要满足"，
//! 于是满血 + 持有 Golden Idol 的玩家永远遇不到这个事件。
//!
//! 为什么仍然是**两个平铺列表**而不是布尔树：真实内容里的需求只有"AND 一组、OR 一组"这一种
//! 形状；一棵树要一套解析器、一套求值器、一套"表里有但没实现"的判据，而两个循环就够了。
//! 树留到真的需要嵌套时再说 —— 那时它值单独一节。
//!
//! ⚠️ **没有** `RequiresAnyAsc`：Moai 的条件与 Ascension 无关。`RequiresAsc` 之所以存在，
//! 是因为 A15 真的改了价目（`The Cleric` 的 Purify 50 → 75）。"以后可能需要"不是加接口的理由。'''

t = sub(t, OLD_HEAD, NEW_HEAD, 'module head')

# ── ② 求值：抽出 read_atoms，加 OR 组 ─────────────────────────────────────────
OLD_EVAL = '''    let mut terms = [0u16; MAX_REQUIREMENTS + 1];
    let count = node
        .term_list_field_or_empty(key, &mut terms)
        .map_err(|error| match error {
            // 列表比缓冲还长 ⇒ 超容量（不是"形状坏了"）。
            IrError::List => RequirementError::TooMany,
            _ => RequirementError::Malformed,
        })?;
    if count > MAX_REQUIREMENTS {
        return Err(RequirementError::TooMany);
    }
    for term in terms.iter().take(count) {
        let atom = NodeRef::new(content, *term);
        if !atom_holds(content, atom, facts)? {
            return Ok(false);
        }
    }
    Ok(true)
}'''

NEW_EVAL = '''    // ── 组间 AND：`Requires`（或 A15 的 `RequiresAsc`）全部成立 ────────────────
    let mut terms = [0u16; MAX_REQUIREMENTS + 1];
    let count = read_atoms(node, key, &mut terms)?;
    for term in terms.iter().take(count) {
        let atom = NodeRef::new(content, *term);
        if !atom_holds(content, atom, facts)? {
            return Ok(false);
        }
    }

    // ── 组内 OR：`RequiresAny` 只要一条成立（§339）────────────────────────────
    //
    // 空列表 = "这一组没要求"，**不是**"永不成立"。这条区分很重要：绝大多数选项没有这个字段，
    // 把它们判成 false 会让整个内容变成死按钮，而且没有任何闸门会红（事件池只是变小）。
    let mut any = [0u16; MAX_REQUIREMENTS + 1];
    let any_count = read_atoms(node, "RequiresAny", &mut any)?;
    if any_count == 0 {
        return Ok(true);
    }
    for term in any.iter().take(any_count) {
        let atom = NodeRef::new(content, *term);
        if atom_holds(content, atom, facts)? {
            return Ok(true);
        }
    }
    Ok(false)
}

/// 读一串条件原子（镜像里是 `F_TERMLIST`）到 `terms`，返回条数。
///
/// 抽出来是因为 §339 之后有**两组**（`Requires` / `RequiresAny`），而"超容量 vs 形状坏了"
/// 这两个错误分支写两遍就会有一遍写错。
fn read_atoms<'a>(
    node: NodeRef<'a>,
    key: &str,
    terms: &mut [u16; MAX_REQUIREMENTS + 1],
) -> Result<usize, RequirementError> {
    let count = node
        .term_list_field_or_empty(key, terms)
        .map_err(|error| match error {
            // 列表比缓冲还长 ⇒ 超容量（不是"形状坏了"）。
            IrError::List => RequirementError::TooMany,
            _ => RequirementError::Malformed,
        })?;
    if count > MAX_REQUIREMENTS {
        return Err(RequirementError::TooMany);
    }
    Ok(count)
}'''

t = sub(t, OLD_EVAL, NEW_EVAL, 'eval + read_atoms')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('run_expr.rs: RequiresAny (AND + OR)')
