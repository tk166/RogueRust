"""第十二轮 Review 的文档侧：审计文档的覆盖边界 + provenance + P1 UX 决策；计划正文的两处事实更正。"""

import io

AUDIT = 'docs/ui-abi-audit.md'
PLAN = 'docs/vibe/RogueRust_UI_Architecture_and_Development_Plan_v1.1_29500d4.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① 审计文档：报告头补 wasm sha + provenance + 覆盖边界 ──────────────────
edit(AUDIT, '''> **基线**：commit `29500d4` + §349；内容镜像 `0x54af44dd`。
> **产物**：本文 + `native/ui_fixtures/p0-scenes.json`（原始 dump，值就是 wasm 说的，未经解释）。''',
     '''> **基线**：commit `29500d4` + §349；内容镜像 `0x54af44dd`；wasm sha256 `4c343910bf68…`。
> **产物**：本文 + `native/ui_fixtures/p0-scenes.json`。
>
> ⚠️ **那个 JSON 里只有 `raw` 是"wasm 原话"**：`facts` 是本脚本从 `raw` 派生的十个
> Adapter 字段（**不是** ABI 断言），`scene` 是 `web/ui_panels.js::resolveScene()` 算出来的。
> 文件里有 `provenance` 字段标明三者的来路（第十二轮 Review P2-B）。''', 'audit header')

edit(AUDIT, '''## 1. 契约断言（机器跑，闸门 24）''',
     '''## 1. 契约断言（机器跑，闸门 24）

> ⚠️ **这是 smoke contract，不是完整的 ABI 验证。** 它证明：52 个导出**存在**、两个向量长度是
> 19/148、若干**选定**的哨兵语义、`i32::MIN` 是合法 seed、18 条场景与**旧分类器自身**的 parity。
>
> 它**没有**证明（第十二轮 Review P1-C，这些留给 P2 的真实契约测试）：
> `rd_env_step` 的"拒绝不改状态"不变性、`_len`/`_into` 的严格字节契约、缓冲区越界行为、
> 52 个函数的签名与返回码全集、以及"18 条场景规则本身正确"（parity 只证明两套实现一致，
> 两边一起错时它也绿）。''', 'audit scope caveat')

# ── ② 审计文档：--report / --check-fixtures 的语义（P1-A / P1-B）──────────
edit(AUDIT, '''`--check` **与内容无关**（不读具体数值），所以内容扩充不会让它变红；`--report` 的产物
**与内容有关**（商店价目、遭遇 id…），换内容后必须重跑，否则本文引用的数字就过期了。''',
     '''`--check` **与内容无关**（不读具体数值），所以内容扩充不会让它变红；`--report` 的产物
**与内容有关**（商店价目、遭遇 id…），换内容后必须重跑，否则本文引用的数字就过期了。

**`--report` 的判定是"计划驱动"的**（第十二轮 Review P1-A）：每条场景先声明
`real`（必须真实到达）或 `synthetic`（允许合成，必须写理由），`real` 的没到达或不落在预期
场景上就 **FAIL**，而且**失败时不写盘**（先构造 + 验证，再写临时文件并 `rename`，P2-A）。
`SC-11a` 的判据是**覆盖层真的出现在 `resolveScene().overlays` 里**，不只是 `pickupPicks > 0`。

**`--check-fixtures` 只证明"元数据新鲜"**（P1-B）：它比 **wasm sha256**（代码）、
**内容指纹**（镜像）与两个向量长度，三者任一变化就报陈旧并说明是哪一种。它**不**证明
"同一份元数据下语义没变" —— 那需要固定种子重新采集并逐字段对比（尚未实现，P2 再做）。''',
     'audit report semantics')

# ── ③ 审计文档：P1 的 UX 决策（actionFor 的单敌行为）──────────────────────
edit(AUDIT, '''## 6. 对计划 v1.1 的两条事实更正（复核时提出，此处复述）''',
     '''## 5b. 一条必须在 P1 之前定下来的**产品决策**（不是 ABI 问题）

`web/ui_render.js::actionFor(options, handSlot, targetSlot)` 现在是：

```js
if (exact) return exact.actionIndex;          // 拖到某个合法目标上
if (list.length === 1) return list[0].actionIndex;   // 只有一条动作 ⇒ 拖到哪儿都算它
return -1;
```

也就是说：**"不需要目标的牌"与"需要目标、但当前只剩一个合法敌人"在拖拽层被合并了** ——
后者拖到空白处也会打出去（打给那个唯一的敌人）。旧页面是**故意**这样的（少一次点击），
但它是否适合 3D/触摸，是**产品决策**：

| 情形 | 旧行为 | 3D 需要明确的问题 |
|---|---|---|
| 无目标牌，拖到任意位置 | 直接出 | 是否只允许拖到"出牌区"？ |
| 定向牌，多个敌人，拖到空白 | 拒绝（回弹） | 保持 |
| **定向牌，只剩一个敌人，拖到空白** | **直接打它** | **要不要保留？**（触摸时误触会直接出牌） |

⇒ P1 必须**单独**决定并分别测三种情形（空白 / 单敌 / 多敌）。
**parity 测试只能锁"业务语义"（槽位不重排、拒绝时不替玩家选目标），不能替代这条产品决策。**

## 6. 对计划 v1.1 的两条事实更正（复核时提出，此处复述）''', 'audit UX decision')

# ── ④ 计划正文：两处"候选缺口"就地更正 ───────────────────────────────────
edit(PLAN, '''- **Enemy 角色美术标识**：`enemy_name` 可能是展示文本；渲染器不能把本地化后的名称当资源键。优先使用真实 `enemyId`/内容定义键；当前无可靠 ID 时使用中性占位模型，并记录为候选接口缺口。''',
     '''- **Enemy 角色美术标识**（⚠️ **§350 已更正，见 `docs/ui-abi-audit.md` §3.4**）：`rd_env_enemy_name_*`
  返回的是**敌人定义 id**（`acid_slime_m`），**不是**本地化文本 ⇒ 可直接作 AssetRegistry 的资源键，
  **不需要**中性占位，也不是接口缺口。显示文字走 `displayName()`。''', 'plan enemy id')

edit(PLAN, '''  definitionId?: string;  // 仅在有可信来源时填充''',
     '''  definitionId?: string;  // ⚠️ §350 已更正：`rd_env_card_name_*` 返回的就是 card definition id
                          //    （可直接填）。但它**不是**跨动作稳定的 CardInstanceId。''',
     'plan definitionId')
print('audit doc + plan body updated')
