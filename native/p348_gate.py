"""§348 门禁与判据：P1-2（`KNOWN_ABSENT` 里那条已经存在的导出）+ P2-2 夹具。

## P1-2：`KNOWN_ABSENT` 藏着一个**已经存在**的导出

`KNOWN_ABSENT` 的用途是"文档**明说**它不存在"。而 `rd_run_over` 在 §344 就已经导出了，
条目却没删 —— 于是**误删那个导出时，检查器仍然通过**（它把缺失当成"已知不存在"）。
那正是这道闸门的主要目的（"接口删除必须让文档检查失败"）。

⇒ 删掉那一条，并加一条负控：**把导出从源码里去掉，检查器必须报 `MISSING`**。

## P2-2：`pending = 99` 的夹具

兜底原来无条件 ⇒ `SC-??` 不可达。现在兜底要求 `pending === 0`，表外的值落到 `SC-??`，
并且 `describe` 给它一份显式的"未知状态"面板（写出那个值）。
"""

import io

CHECK = 'native/ui_state_check.py'
TEST = 'web/ui_test.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 门禁：删掉那条已经失效的 KNOWN_ABSENT ────────────────────────────────
t = io.open(CHECK, encoding='utf-8').read()
t = sub(t, '''    # §1 的场景表与 §6-G1 都**明说**它还没导出。写出来是为了让读者知道"该补什么"，
    # 而不是让它看起来已经存在 —— 所以它进"明确不存在"这张表，而不是 NOT_UI。
    'rd_run_over': '§1 / §6-G1：标注"尚未导出"，是待补项（G1）',
''',
        '''    # ⚠️ §348（第十轮 Review P1-2）：`rd_run_over` 这一条在 §344 导出它之后**必须删掉**。
    # 留着它的后果是"误删导出时检查器仍然通过"—— 而"接口删除必须让文档检查失败"正是这道
    # 闸门的主要目的。它当时是作为"待补项"加进来的，而待补项一旦补上，这一行就从**豁免**
    # 变成了**漏洞**。
''', 'KNOWN_ABSENT cleanup')
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 夹具：pending = 99 必须显性化 ────────────────────────────────────────
t = io.open(TEST, encoding='utf-8').read()
t = sub(t, '''  // 覆盖：`SCENES` 里每一个 id 都要有夹具（少一个 = 那个场景从没被验证过）。''',
        '''  // §348（P2-2）：**表外的 `pending` 必须显性化**，不能静默落地图。
  // 兜底原来是无条件的，于是 `SC-??` 不可达 —— 将来内核新增一个 `Pending`，页面会把它画成
  // 普通地图，而屏幕上一切正常。这条夹具钉住"它落到 `SC-??` 且说得出那个值"。
  {
    const unknown = { ...BASE, pending: 99 };
    const hit = P.classifyScene(unknown);
    if (hit !== "SC-??") fail(`pending=99 must classify as SC-??, got ${hit}`);
    if (P.scenesMatching(unknown).length !== 0) {
      fail(`pending=99 must match no scene, got ${JSON.stringify(P.scenesMatching(unknown))}`);
    }
    const described = P.describe(unknown);
    if (described.title !== "未知状态") fail(`pending=99 must say so, got ${described.title}`);
    if (!(described.lines || []).some((line) => line.includes("99"))) {
      fail(`pending=99 must name the value, got ${JSON.stringify(described.lines)}`);
    }
  }

  // 覆盖：`SCENES` 里每一个 id 都要有夹具（少一个 = 那个场景从没被验证过）。''',
        'pending 99 fixture')
t = sub(t, '''console.log(`  scene table       classifyScene: 18 fixtures, base scenes unique, overlays stack`);''',
        '''console.log(`  scene table       classifyScene: 18 fixtures, base scenes unique, overlays stack`);
console.log(`  unknown pending   pending=99 => SC-?? with an explicit panel (not the map)`);''',
        'log line')
io.open(TEST, 'w', encoding='utf-8', newline='\n').write(t)
print('§348: KNOWN_ABSENT cleaned + pending=99 fixture')
