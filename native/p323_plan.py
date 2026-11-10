import io

PLAN = 'docs/port-plan.md'

text = io.open(PLAN, encoding='utf-8').read()
assert '## §323' not in text, 'port-plan already has §323'
entry = """
## §323 `masked_bandits` —— 三名册外敌人（Pointy / Romeo / Bear）

wiki 的 `Masked_Bandits` 是本作唯一一处"事件里打三个**不在任何池子里**的敌人"：

| 敌人 | HP（A7） | 招式 |
|---|---|---|
| Pointy | 30（34） | Pointy Special **5×2**（A2 6×2），每回合都用 |
| Romeo | 35-39（37-41） | Mock（什么都不做）→ Agonizing Slash（10 + 2 Weak；A2 12、A17 Weak 3）/ Cross Slash（15；A2 17）交替 |
| Bear | 38-42（40-44） | Bear Hug（**-2 敏捷**；A17 -4）→ Lunge（9 + 9 格挡；A2 10）/ Maul（18；A2 20）交替 |

### 形状

- **7 条新动作** + **3 个 `Monsters` 行** + 事件专属遭遇 `enc_masked_bandits` + 池
  `EncounterTables.MaskedBandits`（事件点名的池**不加幕后缀**，§287 的规矩）。
- 模式用 `last_move` 计数器（与 `slaver_red` 同一套）：动作尾巴写 `prev_move ← last_move`、
  `last_move ← N`，`IntentRules` 按 `last_move` 分派。
- **`Fight: "monster"`** —— wiki 明写这场"不算精英"（对 Preserved Insect / Sling of Courage /
  Black Star / Slaver's Collar 而言）。
- 战后奖励走事件的 `After` 段：`gold_random:25:35` + `relic:red_mask`（wiki：常规卡牌奖励 +
  25-35 金币 + Red Mask）。

### 内容门的五张表（它一次全指出来了）

`INV_MONSTERS`（+3）/ `INV_COUNTS`（monsters 58→61）/ `INV_EVENT_ONLY`（+`enc_masked_bandits`）/
`INV_ACTIONS`（+7）/ `INV_ASC_VARIANTS`（6 条）+ `INV_NO_ASC`（`romeo.mock`）+
`INV_ASC_HP`（34 / 37 / 40）。这就是"加一个敌人"的真实成本：**七处**。

### 两个真踩到的坑

1. **事件池名是内核里的字面量**。`rd-core::content` 有两张 hop 表把
   `"MysteriousSphere" => "EncounterTables.MysteriousSphere"` 写死；漏一条的结果是
   `encounters.ids` 在内容门红（"not read by the kernel"），而**运行期**是"事件点下去报池子不存在"。
2. ★ **内容与 `INV_ACTIONS` 一起错，内容门没有第三只眼**：我给 `bear.lunge` 写了
   `Intent: AttackDefend`（内核只有 6 种：`Unknown/Attack/Defend/Buff/Debuff/Special`），
   内容与这张表**都**写了同一个错值 —— 内容门全绿，只有 `every_encounter_in_the_image_builds…`
   在**第 6 回合**抛 `UnknownIntentKind`。修法不只是改内容：门里加了
   `INTENT_KINDS`（内核 6 种的副本）先对一次，负控把 `AttackDefend` 放回去会立刻红。

### 判据

`rd-wasm` 端到端一条：在 `?` 房开 `masked_bandits` → `[Fight!]` → `rd_run_fight_begin`，
然后**用观察 ABI**读敌人名，断言三个都在（`pointy` / `romeo` / `bear`）。这一层必须测，
因为池名跳表是字面量、遭遇是组合记录 —— 错一环只会"少一个人"。

负控三条各红在预期位置：跳表少一条 / 意图词表外的 `AttackDefend` / 怪物名单少 Pointy。

数字：**61 怪 / 63 遭遇 / 166 敌人动作 / 107 个动作有升阶变体（124 个）**、
事件 31（三幕池 10+14+10 = 34）、镜像 186,244 · core 148,836 B、
`rd-core 811 / rd-run 209 / rd-wasm 167`、units 1190（下限 1186 → 1190）。
**Act 2 事件 10/13 → 11/13**（余 `augmenter` 与明确不做的 `cursed_tome`）。
"""
text = text.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(text)
print('port-plan ok')
