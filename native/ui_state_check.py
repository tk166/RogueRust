"""`docs/ui-state-model.md` 的防腐检查器（`port-plan.md` §337）。

## 它防的是什么

这份文档的每一行都声称"这个字段从 `rd_xxx` 读"。文档只有一种腐烂方式：
**名字不再存在，或者新导出没人登记**。两种都长得像"文档看起来挺好"。

所以判据是机械的：

1. 从 `kernel/rd-wasm/src/*.rs` 抽出全部 `pub extern "C" fn rd_*`；
2. 从文档抽出全部 `rd_[a-z0-9_]+` 提及；
3. **文档提到的每一个都必须存在** —— 防拼错、防"删了导出忘了改文档"；
4. **每一条导出都必须被提到，或在 `NOT_UI` 白名单里** —— 防"加了导出没人登记"。

`NOT_UI` 是唯一允许"存在但没写进文档"的地方，每条带理由。没有理由的白名单和
"漏登记"长得一模一样。

## 反证（`--negative`）

* 往文档里塞一个不存在的名字 ⇒ 必须报 `MISSING`；
* 从白名单里挑一条、删掉文档对它的提及 ⇒ 必须报 `UNLOGGED`。

两条都红才算这条闸门有下限（`port-plan.md` §161.5 的教训：没被反证过的下限等于没有）。
"""

import io
import re
import sys

DOC = 'docs/ui-state-model.md'
SRC = ['kernel/rd-wasm/src/lib.rs', 'kernel/rd-wasm/src/run.rs']

# 存在但**不面向 UI** 的导出。每条都要写理由，否则白名单会变成"漏登记"的藏身处。
NOT_UI = {
    # 基准/自检：只在 tools 与测试里用。
    'rd_env_bench_bookkeeping': 'benchmark hook（不是状态）',
    'rd_env_bench_envelope': 'benchmark hook',
    'rd_env_bench_sizes': 'benchmark hook',
    'rd_env_bench_step_raw': 'benchmark hook',
    'rd_env_selfcheck': '测试用自检（重放同一场战斗比两条观察流）',
    'rd_content_check': '内容自检，不是状态',
    # 缓冲区地址/容量：页面用，但不是"字段"，本文按 `R.txt/E.txt` 抽象掉了。
    'rd_env_observe_buf': '零拷贝缓冲区地址（R.obs 的实现细节）',
    'rd_env_observe_len': '向量长度（布局的守卫，不是字段）',
    'rd_env_scratch_buf': '文本中转缓冲区（R.txt/E.txt 的实现细节）',
    'rd_run_script_buf': '脚本文本缓冲区',
    'rd_run_script_capacity': '脚本文本容量',
    'rd_run_archive_buf': '存档文本缓冲区',
    'rd_run_archive_capacity': '存档文本容量',
    # `_into` 那一半：与 `_len` 成对，本文统一写成 `R.txt(x)` / `E.txt(x)`。
    # 逐条列出会把 60 多条名字塞进白名单，反而更难读；所以用前缀规则处理（见 is_not_ui）。
}

# 文档**明确指出不存在**的名字。这是唯一允许"提到但不该存在"的地方 —— 而且必须带理由，
# 因为"我故意写了个不存在的名字"与"我写错了"从文本上看完全一样。
KNOWN_ABSENT = {
    'rd_env_observe': '§0.3 明说没有它（只有 _buf / _into / _len）；写出来是为了让读者别去找',
    # §1 的场景表与 §6-G1 都**明说**它还没导出。写出来是为了让读者知道"该补什么"，
    # 而不是让它看起来已经存在 —— 所以它进"明确不存在"这张表，而不是 NOT_UI。
    'rd_run_over': '§1 / §6-G1：标注"尚未导出"，是待补项（G1）',
}

# ⚠️ 这里**不再**按 `_len`/`_into` 前缀整片豁免。豁免面越大，"漏登记"越容易藏进去：
# 第一版豁免了全部 41 对，于是 72 条导出"存在但文档没写"却报绿。
# 现在只允许一种情况：`X_into` 在 `X_len` 已被覆盖时才算覆盖（§8 的名字表登记了全部 41 个
# `_len`，所以 `_into` 是**由它推出**的，而不是"反正跳过"）。


def is_not_ui(name):
    return name in NOT_UI


def exports():
    found = set()
    # ⚠️ 必须允许 `unsafe`：`rd_run_replay_from` / `rd_env_observe_into` 都是
    # `pub unsafe extern "C" fn`，第一版正则漏了它们，于是文档点名它们反而报 MISSING。
    pattern = re.compile(r'pub (?:unsafe )?extern "C" fn (rd_[a-z0-9_]+)')
    for path in SRC:
        text = io.open(path, encoding='utf-8').read()
        found.update(pattern.findall(text))
    return found


# §6 是**建议**（"该加什么导出"），§7 里有反证用的假名字 —— 这两段不参与
# "文档提到的必须存在"。段界按标题切，切不到就让检查器红（见 check）。
PROPOSAL_HEAD = '## 6.'
PROPOSAL_TAIL = '## 7.'


def mentionable(doc_text):
    """把"声称存在"的部分切出来：§6 之前 + §7 之后（§7 只讲判据，不含真名）。"""
    head, sep, rest = doc_text.partition(PROPOSAL_HEAD)
    if not sep:
        return doc_text
    tail = rest.partition(PROPOSAL_TAIL)[2]
    return head + tail


def mentioned(doc_text):
    # 只认"像导出"的名字：rd_ 开头、小写+数字+下划线。`rd_wasm` / `rd_core` 这类会被过滤掉
    # （它们后面跟的是 `.` 或 `/`，不匹配 [a-z0-9_]）。
    return set(re.findall(r'\brd_(?:run|env|content)_[a-z0-9_]+\b', doc_text))


def check(doc_text=None, label=''):
    doc_text = doc_text if doc_text is not None else io.open(DOC, encoding='utf-8').read()
    have = exports()
    said = mentioned(mentionable(doc_text))

    missing = sorted(
        name for name in said if name not in have and name not in KNOWN_ABSENT)
    covered = set(said) | set(NOT_UI)
    for name in have:
        if name.endswith('_into') and (name[:-5] + '_len') in covered:
            covered.add(name)
    unlogged = sorted(name for name in have if name not in covered)

    print('%s exports=%d mentioned=%d not_ui=%d' % (
        label or 'UI_STATE', len(have), len(said),
        sum(1 for name in have if is_not_ui(name))))

    ok = True
    if missing:
        ok = False
        print('  MISSING (%d) —— 文档提到了、但源码里没有：' % len(missing))
        for name in missing[:12]:
            print('    - %s' % name)
    if unlogged:
        ok = False
        print('  UNLOGGED (%d) —— 源码里有、但文档没提也不在白名单：' % len(unlogged))
        for name in unlogged[:12]:
            print('    - %s' % name)
    return ok


def main():
    doc = io.open(DOC, encoding='utf-8').read()
    ok = check(doc)

    if '--negative' in sys.argv:
        print('--- 负控 ---')
        # ① 文档里塞一个不存在的名字 ⇒ 必须报 MISSING。
        bogus = doc + '\n| 假字段 | — | — | `rd_run_nonexistent()` | — |\n'
        first = check(bogus, '负控①')
        # ⚠️ 证据串一律 ASCII：PS5.1 按 ANSI 解码子进程输出，中文会乱码，
        # `-MustMatch` 就永远匹配不到（实测：闸门红在一句"看起来对"的话上）。
        print('  NEGCTL1 %s' % ('RED' if not first else 'GREEN_NOT_CAUGHT'))
        # ② 白名单里挑一条不靠前缀豁免的，同时删掉文档对它的提及 ⇒ 必须报 UNLOGGED。
        # 挑一条**文档里点名过、且不靠 `_len/_into` 前缀豁免**的导出，把提及删掉。
        victim = 'rd_run_campfire_options'
        assert victim in doc, '文档里必须先提到 %s 才能做这条负控' % victim
        stripped = doc.replace(victim, '篝火位掩码导出')
        second = check(stripped, '负控②')
        print('  NEGCTL2 %s' % ('RED' if not second else 'GREEN_NOT_CAUGHT'))
        ok = ok and not first and not second

    print('UI_STATE_CHECK', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
