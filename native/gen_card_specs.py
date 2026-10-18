#!/usr/bin/env python3
"""gen_card_specs.py -- 从 RDCF 内容镜像生成 `native/card_specs.json`（62 张卡的规范描述）。

# 这份文件是什么

跨语言对拍（`native/fight_diff.py`）逐卡比较 Rust 内核与 C# 参考实现。**卡定义 id 进哈希**，
所以两边必须打同一张卡：同一个 id、同一段程序、同一个费用、同一个落区。Rust 侧直接读镜像；
C# 侧**没有 RDCF 读取器**，只能按镜像的事实 author —— 而"手抄一遍"就是会静默腐烂的东西。

所以这里产出**一份从镜像派生的规范描述**，C# 侧在运行时读它、把它翻译成引擎的 typed node，
`fight_diff.py` 再把 C# 落地的结果与镜像逐键对差。这份 json 的唯一真相是镜像：

* 它由本脚本生成，`fight_diff.py` 每次运行都会**在内存里重新派生一遍并与磁盘上的文件逐字节比对**，
  镜像变了而文件没重生成 ⇒ 响亮失败（"陈旧产物"比"没有产物"更毒）。

# 输出结构（字段的取舍就是契约）

    {
      "format": 1,
      "image": "tools/contentc/out/content.core.rdcf",
      "image_bytes": 85616,
      "card_count": 62,
      "statuses": [ {id, polarity, stacking, tags, uses_stacks, uses_duration, uses_charges,
                     passive_modifiers[], triggers[]} ],   # 卡程序引用到的（含触发器程序的根节点）
      "cards":    [ {index, id, package, costs[], tags[], played_zone, turn_end_zone,
                     retain, is_action, queue_on_play, lifecycle, play_condition,
                     program{id, depth, steps, root}} ]
    }

**显式默认**：镜像在线上省略与默认值相等的键，所以本文件把每个可省字段都写成显式的
（`resultKey: null`、`charges: 0`、`ignoresBlock: false`、`element: null` …）。
"缺席"与"显式默认"在 C# 侧必须不可区分 —— 写死的形态让这条规则看得见。

# 拒绝策略

不认识的节点种类 / 选择器 / 表达式 / 枚举值一律**抛错并指出是哪张卡的哪条路径**，
不做"跳过这张卡"。`native/fight_diff.py` 把这份脚本的失败当成闸门失败。

    python native/gen_card_specs.py            # 写 native/card_specs.json
    python native/gen_card_specs.py --check    # 只校验磁盘上的文件是否与镜像一致
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENTC = os.path.join(ROOT, "tools", "contentc")
IMAGE_REL = "tools/contentc/out/content.core.rdcf"
IMAGE = os.path.join(ROOT, "tools", "contentc", "out", "content.core.rdcf")
OUT = os.path.join(ROOT, "native", "card_specs.json")
SPEC_FORMAT = 2

if CONTENTC not in sys.path:
    sys.path.insert(0, CONTENTC)


class SpecError(RuntimeError):
    """镜像里出现了本脚本不认识/表示不了的东西 —— 不许跳过，必须响亮失败。"""


# ===========================================================================
# 小工具
# ===========================================================================

def unwrap(value):
    """`F_STR` 字段带一层 {value:|Value:} 包装（FLAG_WRAP_LOWER/UPPER）；剥掉它。"""
    if isinstance(value, dict):
        for key in ("value", "Value"):
            if key in value:
                return value[key]
    return value


def get(body, key, where):
    """取一个**必填**字段；缺席说明镜像的形态变了，必须响亮失败。"""
    if key not in body:
        raise SpecError(f"{where}: 缺少字段 `{key}`（镜像形态变了？实际字段：{sorted(body)}）")
    return body[key]


def optional(body, key, default):
    return body[key] if key in body else default


def want_fields(body, allowed, where, allow_empty_children=False):
    """拒绝**不认识**的字段。

    这条比"读到什么算什么"重要得多：镜像以后多出一个字段（比如 `forEachCardInZone.MarkFilter`），
    悄悄丢弃它 = 两侧的程序不一样而闸门看不出。宁可砸在这里。
    """
    extra = sorted(set(body) - set(allowed))
    if extra:
        raise SpecError(f"{where}: 有不认识的字段 {extra}（已知：{sorted(allowed)}）")
    if allow_empty_children and "Children" in body and body["Children"]:
        raise SpecError(f"{where}.Children 非空（叶子节点不该有子节点）")


def enum_of(body, key, allowed, where):
    value = get(body, key, where)
    if value not in allowed:
        raise SpecError(f"{where}.{key} = {value!r}，不在已知取值 {sorted(allowed)} 里")
    return value


# ===========================================================================
# 节点 / 表达式 / 选择器 → 规范 JSON
#
# 关键词是本文件自己的 camelCase，值一律显式。字段顺序不重要（json 里按 key 排序写），
# 但**字段集合**是契约：C# 侧按同一张表翻译，少一个字段就是少一条语义。
# ===========================================================================

SELECTORS = {"sel.eventTarget": "eventTarget", "sel.source": "source", "sel.allEnemies": "allEnemies",
             "sel.allAllies": "allAllies"}
SELECTOR_FIELDS = {"Cardinality", "RequiredContextCapabilities"}

# 每种节点**允许**出现的字段。镜像省略与默认值相等的键，所以可选字段在这里是"允许但不要求"。
#
# ⚠️ `node.conditional` / `node.loseResource` 的 `Children`：参考的 `IEffectNode.Children`
# 是**第二个视图**（`ConditionalEffectNode` 的 `Children` 就是 `[Then]` 或 `[Then, Else]`，
# `CombatJson.cs:150-197` 只在"构造函数收 children"的类型上写它）。所以 spec 不把它当独立语义，
# 而是**校验它确实是 Then/Else 的投影**（见 `node()`）：丢掉一个和树矛盾的 `Children` 会让
# "两侧程序一样"这句话变成假的。
NODE_FIELDS = {
    "node.noop": set(),
    "node.sequence": {"Children"},
    "node.dealDamage": {"Amount", "Element", "IgnoresBlock", "Kind", "ResultKey", "TargetSelector"},
    "node.applyStatus": {"Charges", "DurationTurns", "ResultKey", "SourceSelector", "Stacks",
                         "StatusDefinitionId", "TargetSelector", "UnrefusableBy"},
    "node.gainBlock": {"Amount", "ResultKey", "TargetSelector"},
    "node.drawCards": {"Count", "ResultKey", "TargetSelector"},
    "node.gainResource": {"Amount", "DefaultMax", "ResourceId", "ResultKey", "TargetSelector"},
    "node.loseResource": {"Amount", "Children", "ResourceId", "ResultKey", "TargetSelector"},
    "node.createCardInstance": {"CardDefinitionId", "Count", "ResultKey", "TargetSelector", "ToZone"},
    "node.forEachCardInZone": {"Body", "DefinitionFilter", "MaxIterations", "OwnerSelector",
                               "TagFilter", "TakeFirst", "Zone"},
    "node.moveCardToZone": {"CardExpression", "OwnerSelector", "Placement", "ResultKey", "ToZone"},
    "node.modifyStatusStacks": {"Children", "Delta", "ResultKey", "StatusDefinitionId", "TargetSelector"},
    "node.setCombatantCounter": {"Amount", "CounterId", "Relative", "TargetSelector"},
    "node.conditional": {"Children", "Condition", "Else", "Then"},
}
EXPRESSION_FIELDS = {
    "const": {"Value"},
    "multiply": {"Left", "Right"},
    "add": {"Left", "Right"},
    "subtract": {"Left", "Right"},
    "min": {"Left", "Right"},
    # `DivideExpression`（`EffectProgramExpressions.cs:551`）的两个操作数叫
    # Dividend/Divisor，还有个 `ZeroPolicy`（`expr.rs:236` 的 `check_zero_policy`）。
    "divide": {"Dividend", "Divisor", "ZeroPolicy"},
    "combatantStatusStacks": {"Selector", "StatusId"},
    "combatantCounter": {"CounterId", "Selector"},
}
# 布尔表达式（`node.conditional` 的 `Condition`）。参考用同一个 `ICombatExpression<TContext, bool>`
# 注册表（`CombatJson.cs` 的 `Register("compare", typeof(ComparisonExpression<>))`）。
CONDITION_FIELDS = {
    "compare": {"Left", "Op", "Right"},
}
CARD_EXPRESSION_FIELDS = {"cardInstance.iterated": set()}

# 镜像里每个选择器都带 `Cardinality` / `RequiredContextCapabilities` 两格 —— 但**不是每个**：
# `sel.rs:133` 的实测是"24 条 `sel.*` 里只有 4 条带这个字段"。这两格不是"我们授权的参数"，
# 而是选择器在参考实现里的固定属性（`CombatantTargetSelectors.cs:77/115/154`：Source/EventTarget
# 都是 ZeroOrOne；`AllAlliesOfSourceCombatantTargetSelector` 在镜像里**一个字段都不写**）。
# 所以这里**钉住**它们：`None` 表示"这两格必须缺席"，写成别的形状立刻砸下来。
SELECTOR_CAPABILITIES = {
    "eventTarget": ("ZeroOrOne", "EventTarget"),
    "source": ("ZeroOrOne", "Source"),
    "allEnemies": ("ZeroOrOne", "AllEnemiesOfSource"),
    "allAllies": (None, None),
}

# `IntentKind`（参考 `IntentKind` 枚举：Unknown/Attack/Defend/Buff/Debuff/Special`）。
INTENT_KINDS = {"Unknown", "Attack", "Defend", "Buff", "Debuff", "Special"}
DAMAGE_KINDS = {"Direct", "DamageOverTime"}
# `DivideByZeroPolicy`（`EffectProgramExpressions.cs:549`；内核 `expr.rs:200-206`）。缺席 = ReturnZero。
ZERO_POLICIES = {"ReturnZero", "Fault"}
# `ComparisonOperator`（`EffectProgramExpressions.cs:360-368`）。
COMPARE_OPS = {"Equal", "NotEqual", "Less", "LessOrEqual", "Greater", "GreaterOrEqual"}
# `CardZone`（`Cards/CardZones.cs:3-22`）的全部成员。
CARD_ZONES = {"DrawPile", "Hand", "DiscardPile", "ExhaustPile", "BanishedPile", "QueuePile", "SetAsidePile"}
PLACEMENTS = {"Bottom", "Top"}
POLARITIES = {"Neutral", "Buff", "Debuff"}
STACKINGS = {"CreateSeparateInstance", "MergeWithExistingInstance"}


def selector(value, where):
    if value is None:
        return None
    kind = get(value, "kind", where)
    name = SELECTORS.get(kind)
    if name is None:
        raise SpecError(f"{where}: 不认识的选择器 `{kind}`（已知：{sorted(SELECTORS)}）")
    body = value.get("value") or {}
    want_fields(body, SELECTOR_FIELDS, where + "(" + kind + ")")
    want_card, want_cap = SELECTOR_CAPABILITIES[name]
    if want_card is None:
        # "这两格必须缺席"——镜像写了就意味着出现了一种新的选择器形态，先弄清它再放行。
        if body:
            raise SpecError(
                f"{where}: 选择器 `{kind}` 在镜像里**不带** Cardinality/RequiredContextCapabilities，"
                f"这里却有 {sorted(body)} —— 镜像是新形态，先核对参考实现再放行")
        return {"kind": name}
    got_card = optional(body, "Cardinality", want_card)
    got_cap = optional(body, "RequiredContextCapabilities", want_cap)
    if (got_card, got_cap) != (want_card, want_cap):
        raise SpecError(
            f"{where}: 选择器 `{kind}` 的 (Cardinality, RequiredContextCapabilities) = "
            f"({got_card!r}, {got_cap!r})，而这三种选择器在参考实现里固定是 "
            f"({want_card!r}, {want_cap!r}) —— 镜像里出现了第四种形态，先弄清它再放行")
    return {"kind": name}


def expression(value, where):
    if value is None:
        return None
    kind = get(value, "kind", where)
    body = value.get("value") or {}
    allowed = EXPRESSION_FIELDS.get(kind)
    if allowed is None:
        raise SpecError(f"{where}: 不认识的表达式 `{kind}`")
    want_fields(body, allowed, f"{where}({kind})")
    if kind == "const":
        return {"kind": "const", "value": int(get(body, "Value", where))}
    if kind in ("multiply", "add", "subtract", "min"):
        return {"kind": kind,
                "left": expression(get(body, "Left", where), where + ".Left"),
                "right": expression(get(body, "Right", where), where + ".Right")}
    if kind == "divide":
        return {"kind": "divide",
                "dividend": expression(get(body, "Dividend", where), where + ".Dividend"),
                "divisor": expression(get(body, "Divisor", where), where + ".Divisor"),
                # 缺席 = `ReturnZero`（`EffectProgramExpressions.cs:561` 的接口默认值，内核 `expr.rs:236` 同）。
                "zero_policy": enum_of(body, "ZeroPolicy", ZERO_POLICIES, where)
                               if "ZeroPolicy" in body else "ReturnZero"}
    if kind == "combatantStatusStacks":
        return {"kind": "combatantStatusStacks",
                "selector": selector(get(body, "Selector", where), where + ".Selector"),
                "status": str(unwrap(get(body, "StatusId", where)))}
    if kind == "combatantCounter":
        return {"kind": "combatantCounter",
                "counter": str(unwrap(get(body, "CounterId", where))),
                "selector": selector(get(body, "Selector", where), where + ".Selector")}
    raise SpecError(f"{where}: 不认识的表达式 `{kind}`")


def condition(value, where):
    """`ICombatExpression<TContext, bool>` —— 只有 `compare` 出现在本镜像里。"""
    if value is None:
        raise SpecError(f"{where}: 条件是 null（`node.conditional` 没有 Then 之外的一半语义）")
    kind = get(value, "kind", where)
    body = value.get("value") or {}
    allowed = CONDITION_FIELDS.get(kind)
    if allowed is None:
        raise SpecError(f"{where}: 不认识的条件表达式 `{kind}`（已知：{sorted(CONDITION_FIELDS)}）")
    want_fields(body, allowed, f"{where}({kind})")
    if kind == "compare":
        return {"kind": "compare",
                "left": expression(get(body, "Left", where), where + ".Left"),
                "op": enum_of(body, "Op", COMPARE_OPS, where),
                "right": expression(get(body, "Right", where), where + ".Right")}
    raise SpecError(f"{where}: 不认识的条件表达式 `{kind}`")


def card_expression(value, where):
    if value is None:
        return None
    kind = get(value, "kind", where)
    allowed = CARD_EXPRESSION_FIELDS.get(kind)
    if allowed is None:
        raise SpecError(f"{where}: 不认识的卡实例表达式 `{kind}`")
    want_fields(value.get("value") or {}, allowed, f"{where}({kind})")
    if kind == "cardInstance.iterated":
        return {"kind": "iterated"}
    raise SpecError(f"{where}: 不认识的卡实例表达式 `{kind}`")


def node(value, where):
    if value is None:
        return None
    kind = get(value, "kind", where)
    body = value.get("value") or {}
    allowed = NODE_FIELDS.get(kind)
    if allowed is None:
        raise SpecError(f"{where}: 不认识的节点种类 `{kind}`（已知：{sorted(NODE_FIELDS)}）")
    want_fields(body, allowed, f"{where}({kind})",
                allow_empty_children=kind not in ("node.sequence", "node.conditional"))

    def path(field):
        return where + "." + field

    if kind == "node.noop":
        return {"kind": "noop"}
    if kind == "node.sequence":
        children = get(body, "Children", where)
        return {"kind": "sequence",
                "children": [node(child, f"{where}.children[{i}]") for i, child in enumerate(children)]}
    if kind == "node.dealDamage":
        return {
            "kind": "dealDamage",
            "amount": expression(get(body, "Amount", where), path("Amount")),
            "element": None if optional(body, "Element", None) is None
                       else str(unwrap(body["Element"])),
            "ignoresBlock": bool(optional(body, "IgnoresBlock", False)),
            "damageKind": enum_of(body, "Kind", DAMAGE_KINDS, where) if "Kind" in body else "Direct",
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.applyStatus":
        if optional(body, "UnrefusableBy", None) is not None:
            raise SpecError(
                f"{where}: `UnrefusableBy` 非空（{body['UnrefusableBy']!r}）—— 本轮的 authoring 不支持它")
        return {
            "kind": "applyStatus",
            "charges": int(optional(body, "Charges", 0)),
            "duration": int(optional(body, "DurationTurns", 0)),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "source": selector(optional(body, "SourceSelector", None), path("SourceSelector")),
            "stacks": expression(get(body, "Stacks", where), path("Stacks")),
            "status": str(unwrap(get(body, "StatusDefinitionId", where))),
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.gainBlock":
        return {
            "kind": "gainBlock",
            "amount": expression(get(body, "Amount", where), path("Amount")),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.drawCards":
        return {
            "kind": "drawCards",
            "count": expression(get(body, "Count", where), path("Count")),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.gainResource":
        return {
            "kind": "gainResource",
            "amount": expression(get(body, "Amount", where), path("Amount")),
            "defaultMax": optional(body, "DefaultMax", None),
            "resource": str(unwrap(get(body, "ResourceId", where))),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.createCardInstance":
        return {
            "kind": "createCardInstance",
            "card": str(unwrap(get(body, "CardDefinitionId", where))),
            "count": expression(get(body, "Count", where), path("Count")),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
            "toZone": enum_of(body, "ToZone", CARD_ZONES, where),
        }
    if kind == "node.forEachCardInZone":
        return {
            "kind": "forEachCardInZone",
            "body": node(get(body, "Body", where), path("Body")),
            "definitionFilter": None if optional(body, "DefinitionFilter", None) is None
                                else str(unwrap(body["DefinitionFilter"])),
            "maxIterations": int(optional(body, "MaxIterations", 64)),
            "owner": selector(get(body, "OwnerSelector", where), path("OwnerSelector")),
            "tagFilter": None if optional(body, "TagFilter", None) is None
                         else str(unwrap(body["TagFilter"])),
            "takeFirst": optional(body, "TakeFirst", None),
            "zone": enum_of(body, "Zone", CARD_ZONES, where),
        }
    if kind == "node.moveCardToZone":
        return {
            "kind": "moveCardToZone",
            "card": card_expression(get(body, "CardExpression", where), path("CardExpression")),
            "owner": selector(get(body, "OwnerSelector", where), path("OwnerSelector")),
            "placement": enum_of(body, "Placement", PLACEMENTS, where) if "Placement" in body else "Bottom",
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "toZone": enum_of(body, "ToZone", CARD_ZONES, where),
        }
    if kind == "node.modifyStatusStacks":
        return {
            "kind": "modifyStatusStacks",
            "delta": expression(get(body, "Delta", where), path("Delta")),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "status": str(unwrap(get(body, "StatusDefinitionId", where))),
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.loseResource":
        if get(body, "Children", where):
            raise SpecError(f"{where}: `loseResource` 是叶子节点，`Children` 却有内容")
        return {
            "kind": "loseResource",
            "amount": expression(get(body, "Amount", where), path("Amount")),
            "resource": str(unwrap(get(body, "ResourceId", where))),
            "resultKey": None if optional(body, "ResultKey", None) is None else "set",
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.setCombatantCounter":
        # `SetCombatantCounterNode`（`EffectProgramNativeNodes.cs:655-690`）：
        # `Relative` 的接口默认是 true（`relative = true`），镜像写 `false` 就表示"置位"。
        return {
            "kind": "setCombatantCounter",
            "amount": expression(get(body, "Amount", where), path("Amount")),
            "counter": str(unwrap(get(body, "CounterId", where))),
            "relative": bool(optional(body, "Relative", True)),
            "target": selector(get(body, "TargetSelector", where), path("TargetSelector")),
        }
    if kind == "node.conditional":
        then_branch = node(get(body, "Then", where), path("Then"))
        else_branch = node(optional(body, "Else", None), path("Else"))
        # `Children` 是 Then/Else 的**第二个视图**（`ConditionalEffectNode.Children`），
        # 丢掉它不丢语义 —— 但前提是它确实是那个投影。断言它，而不是默默忽略。
        projection = [then_branch] + ([else_branch] if else_branch is not None else [])
        raw_children = get(body, "Children", where)
        if len(raw_children) not in (1, len(projection)):
            raise SpecError(
                f"{where}: `conditional.Children` 有 {len(raw_children)} 项，而 Then/Else 的投影是 "
                f"{len(projection)} 项 —— 镜像的 `Children` 不再是 Then/Else 的视图了")
        return {
            "kind": "conditional",
            "condition": condition(get(body, "Condition", where), path("Condition")),
            "then": then_branch,
            "else": else_branch,
        }
    raise SpecError(f"{where}: 不认识的节点种类 `{kind}`")


# ===========================================================================
# 规范文本（与 native/fight_diff.py 的 node_text / OracleExports.Cards.cs 的 NodeText 逐字节相同）
#
# 字段按字母序；每个可选字段都写成显式的 none —— 镜像省略默认值，所以"缺席"必须等于"显式默认"。
# ===========================================================================

def selector_text(value):
    return "none" if value is None else value["kind"]


def expression_text(value):
    if value is None:
        return "none"
    kind = value["kind"]
    if kind == "const":
        return "const(%d)" % value["value"]
    if kind in ("multiply", "add", "subtract", "min"):
        return "%s(%s,%s)" % (kind, expression_text(value["left"]), expression_text(value["right"]))
    if kind == "divide":
        return "divide(%s,%s,%s)" % (expression_text(value["dividend"]),
                                     expression_text(value["divisor"]), value["zero_policy"])
    if kind == "combatantStatusStacks":
        return "combatantStatusStacks(selector=%s;status=%s)" % (
            selector_text(value["selector"]), value["status"])
    if kind == "combatantCounter":
        return "combatantCounter(counter=%s;selector=%s)" % (
            value["counter"], selector_text(value["selector"]))
    if kind == "iterated":
        return "iterated"
    raise SpecError("expression_text: 不认识 %r" % (kind,))


def condition_text(value):
    if value is None:
        return "none"
    if value["kind"] == "compare":
        return "compare(left=%s;op=%s;right=%s)" % (
            expression_text(value["left"]), value["op"], expression_text(value["right"]))
    raise SpecError("condition_text: 不认识 %r" % (value["kind"],))


def bool_text(value):
    return "true" if value else "false"


def result_key_text(value):
    return "none" if value is None else "set"


def node_text(value):
    if value is None:
        return "none"
    kind = value["kind"]
    if kind == "noop":
        return "noop"
    if kind == "sequence":
        return "sequence(" + ",".join(node_text(c) for c in value["children"]) + ")"
    if kind == "dealDamage":
        return ("dealDamage(amount=%s;element=%s;ignores_block=%s;kind=%s;result_key=%s;target=%s)"
                % (expression_text(value["amount"]),
                   "none" if value["element"] is None else value["element"],
                   bool_text(value["ignoresBlock"]), value["damageKind"],
                   result_key_text(value["resultKey"]), selector_text(value["target"])))
    if kind == "applyStatus":
        return ("applyStatus(charges=%d;duration=%d;result_key=%s;source=%s;stacks=%s;status=%s;target=%s)"
                % (value["charges"], value["duration"], result_key_text(value["resultKey"]),
                   selector_text(value["source"]), expression_text(value["stacks"]), value["status"],
                   selector_text(value["target"])))
    if kind == "gainBlock":
        return "gainBlock(amount=%s;result_key=%s;target=%s)" % (
            expression_text(value["amount"]), result_key_text(value["resultKey"]),
            selector_text(value["target"]))
    if kind == "drawCards":
        return "drawCards(count=%s;result_key=%s;target=%s)" % (
            expression_text(value["count"]), result_key_text(value["resultKey"]),
            selector_text(value["target"]))
    if kind == "gainResource":
        return "gainResource(amount=%s;default_max=%s;resource=%s;result_key=%s;target=%s)" % (
            expression_text(value["amount"]),
            "none" if value["defaultMax"] is None else str(value["defaultMax"]),
            value["resource"], result_key_text(value["resultKey"]), selector_text(value["target"]))
    if kind == "createCardInstance":
        return "createCardInstance(card=%s;count=%s;result_key=%s;target=%s;to_zone=%s)" % (
            value["card"], expression_text(value["count"]), result_key_text(value["resultKey"]),
            selector_text(value["target"]), value["toZone"])
    if kind == "forEachCardInZone":
        return ("forEachCardInZone(body=%s;definition_filter=%s;max_iterations=%d;owner=%s;tag_filter=%s;"
                "take_first=%s;zone=%s)"
                % (node_text(value["body"]),
                   "none" if value["definitionFilter"] is None else value["definitionFilter"],
                   value["maxIterations"], selector_text(value["owner"]),
                   "none" if value["tagFilter"] is None else value["tagFilter"],
                   "none" if value["takeFirst"] is None else str(value["takeFirst"]),
                   value["zone"]))
    if kind == "moveCardToZone":
        return "moveCardToZone(card=%s;owner=%s;placement=%s;result_key=%s;to_zone=%s)" % (
            expression_text(value["card"]), selector_text(value["owner"]), value["placement"],
            result_key_text(value["resultKey"]), value["toZone"])
    if kind == "modifyStatusStacks":
        return "modifyStatusStacks(delta=%s;result_key=%s;status=%s;target=%s)" % (
            expression_text(value["delta"]), result_key_text(value["resultKey"]), value["status"],
            selector_text(value["target"]))
    if kind == "loseResource":
        return "loseResource(amount=%s;resource=%s;result_key=%s;target=%s)" % (
            expression_text(value["amount"]), value["resource"], result_key_text(value["resultKey"]),
            selector_text(value["target"]))
    if kind == "setCombatantCounter":
        return "setCombatantCounter(amount=%s;counter=%s;relative=%s;target=%s)" % (
            expression_text(value["amount"]), value["counter"], bool_text(value["relative"]),
            selector_text(value["target"]))
    if kind == "conditional":
        return "conditional(condition=%s;else=%s;then=%s)" % (
            condition_text(value["condition"]), node_text(value["else"]), node_text(value["then"]))
    raise SpecError("node_text: 不认识 %r" % (kind,))


# ===========================================================================
# 从镜像派生
# ===========================================================================

def _status_refs(value, into):
    """把规范树里引用到的状态 id 收进 `into`。

    两处会引用状态：节点 `applyStatus` / `modifyStatusStacks` 的 `status`，
    以及表达式 `combatantStatusStacks` 的 `status`。一处漏了就会在 C# 注册表编译时
    报"未知状态"—— 那时离真正的原因已经很远了。
    """
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind in ("applyStatus", "modifyStatusStacks"):
            into.append(value["status"])
        elif kind == "combatantStatusStacks":
            into.append(value["status"])
        for key in sorted(value):
            _status_refs(value[key], into)
    elif isinstance(value, list):
        for item in value:
            _status_refs(item, into)


def _created_cards(value, into):
    """把规范树里 `createCardInstance` 指向的卡 id 收进 `into`。"""
    if isinstance(value, dict):
        if value.get("kind") == "createCardInstance":
            into.append(value["card"])
        for key in sorted(value):
            _created_cards(value[key], into)
    elif isinstance(value, list):
        for item in value:
            _created_cards(item, into)


def status_closure(rom, roots, where):
    """一组程序根 → 它们引用到的状态的**传递闭包**（`status_id -> status_spec`）。

    为什么要闭包：状态自己的触发器程序还会引用状态（`bookworm` 的 TurnStarted 触发器改
    `paperwork`）。漏一层就会在 C# 注册表编译时报"未知状态"，而那时离原因已经很远。
    """
    cache = {}
    queue = []
    for root in roots:
        _status_refs(root, queue)
    while queue:
        status_id = queue.pop()
        if status_id in cache:
            continue
        spec = status_spec(rom, status_id, where)
        for trigger in spec["triggers"]:
            _status_refs(trigger["program"]["root"], queue)
        cache[status_id] = spec
    return cache


def enemy_actions(rom):
    """镜像的 `EACT` 全表 → 规范描述列表（**一条都不许跳过**），并逐个查清归属敌人。

    归属靠两条事实交叉确认：

    * 动作 id 的前缀（`<敌人>.<动作>`）必须是某个真实敌人 id —— 镜像里没有"敌人表"，
      敌人只作为 `ENCT` 记录里嵌的对象存在；
    * 如果这条动作被某个敌人的 `Actions` 列表点名，点名者必须**就是**那个前缀。

    5 条动作只被 `IntentRules` 引用、不在任何 `Actions` 列表里（例如 `minute_moth.wingbeat_delay`）：
    它们仍然有前缀，所以照样归到那个敌人名下，并把这条差别记成 `listed=false` 而不是猜。
    """
    owners = {}
    enemy_ids = set()
    for enc in rom._rows("ENCT"):
        for enemy in enc.get("Enemies") or []:
            enemy_id = enemy.get("Id")
            if not isinstance(enemy_id, str):
                raise SpecError(f"ENCT `{unwrap(enc.get('Id'))}`: 敌人没有字符串 Id（{enemy_id!r}）")
            enemy_ids.add(enemy_id)
            for action in enemy.get("Actions") or []:
                action_id = unwrap(action)
                owners.setdefault(action_id, set()).add(enemy_id)

    out = []
    for index, rec in enumerate(rom._rows("EACT")):
        where = f"enemy_action[{index}]"
        want_fields(rec, {"Id", "Intent", "PackageId", "Program"}, where)
        action_id = str(unwrap(get(rec, "Id", where)))
        where = f"enemy_action({action_id})"
        if "." not in action_id:
            raise SpecError(f"{where}: 动作 id 里没有 `.`，推不出归属敌人")
        owner = action_id.split(".")[0]
        if owner not in enemy_ids:
            raise SpecError(
                f"{where}: 前缀 `{owner}` 不是镜像里任何敌人 id（敌人只存在于 ENCT 的 Enemies 里）")
        named = owners.get(action_id, set())
        if named and owner not in named:
            raise SpecError(
                f"{where}: 前缀说是 `{owner}`，但 ENCT 里点名这条动作的敌人是 {sorted(named)} —— "
                f"归属不再能从 id 前提取，先弄清它")

        intent = get(rec, "Intent", where)
        want_fields(intent, {"Kind"}, where + ".Intent")
        program = optional(rec, "Program", None)
        if program is None:
            raise SpecError(f"{where}: `Program` 是 null —— 没有程序的动作不算「已 author」")

        out.append({
            "index": index,
            "id": action_id,
            "enemy": owner,
            "listed": bool(named),
            "package": optional(rec, "PackageId", "scenario"),
            "intent": enum_of(intent, "Kind", INTENT_KINDS, where + ".Intent"),
            "program": program_spec(program, where),
            "statuses": [],
        })

    # 每条动作需要哪些状态定义（传递闭包）：C# 侧只 author 它自己那条动作要的，
    # 这样"少 author 一个状态"不会被别处的定义掩盖。
    for action in out:
        closure = status_closure(rom, [action["program"]["root"]], "status")
        action["statuses"] = sorted(closure)
    return out


def status_spec(rom, status_id, where):
    hit = rom.lookup(status_id)
    if hit is None:
        raise SpecError(f"{where}: 镜像里没有状态 `{status_id}`（模式程序引用了不存在的状态）")
    if hit[0] != 2:
        raise SpecError(f"{where}: `{status_id}` 在镜像里不是 STATUS 行（实体类别 {hit[0]}）")
    rec = rom.entity("STATUS", hit[1])
    prefix = f"{where}({status_id})"

    # 这些机制是 C# 侧这一轮**没有** author 的；镜像里非空就等于"两边跑的不是同一张卡"。
    for key in ("DeathPrevention", "DebuffBlock", "IncomingStatusDelay", "Disclosure",
                "Prevention", "Amplification"):
        if optional(rec, key, None) is not None:
            raise SpecError(f"{prefix}: `{key}` 非空，本轮的 authoring 不支持它")
    if rec.get("CombatRules"):
        raise SpecError(f"{prefix}: `CombatRules` 非空（{len(rec['CombatRules'])} 条），本轮的 authoring 不支持它")

    modifiers = []
    for index, spec in enumerate(rec.get("PassiveModifiers") or []):
        mwhere = f"{prefix}.PassiveModifiers[{index}]"
        want_fields(spec, {"Pipeline", "Operation", "Magnitude", "Priority", "RestrictDamageKind",
                           "AppliesToStatusId", "RestrictSourceCardTag", "MagnitudeExpression",
                           "RestrictElement"}, mwhere)
        for key in ("MagnitudeExpression", "RestrictElement", "AppliesToStatusId", "RestrictSourceCardTag"):
            if optional(spec, key, None) is not None:
                raise SpecError(f"{mwhere}: `{key}` 非空，本轮的 authoring 不支持它")
        modifiers.append({
            "pipeline": get(spec, "Pipeline", mwhere),
            "operation": get(spec, "Operation", mwhere),
            "magnitude": int(get(spec, "Magnitude", mwhere)),
            "priority": int(optional(spec, "Priority", 100)),
            # DamageKind? 的默认是 Direct（`PassiveModifiers.cs:80-88`）；镜像省略与默认相等的键。
            "restrictDamageKind": optional(spec, "RestrictDamageKind", "Direct"),
        })

    triggers = []
    for index, trigger in enumerate(rec.get("Triggers") or []):
        twhere = f"{prefix}.Triggers[{index}]"
        want_fields(trigger, {"Event", "Program"}, twhere)
        triggers.append({
            "event": get(trigger, "Event", twhere),
            "program": program_spec(get(trigger, "Program", twhere), twhere),
        })

    tags = optional(rec, "Tags", [])
    for tag in tags:
        if not isinstance(unwrap(tag), str):
            raise SpecError(f"{prefix}: Tags 里出现了非字符串 {tag!r}")

    return {
        "id": status_id,
        "package": optional(rec, "PackageId", "scenario"),
        "polarity": enum_of(rec, "Polarity", POLARITIES, prefix),
        "stacking": enum_of(rec, "StackingBehavior", STACKINGS, prefix),
        "tags": [str(unwrap(tag)) for tag in tags],
        "uses_stacks": bool(optional(rec, "UsesStacks", False)),
        "uses_duration": bool(optional(rec, "UsesDuration", False)),
        "uses_charges": bool(optional(rec, "UsesCharges", False)),
        "passive_modifiers": modifiers,
        "triggers": triggers,
    }


def program_spec(program, where):
    """镜像里的 `Program` 对象 → 规范描述。字段表是钉死的（`Id/MaxNodeDepth/MaxProgramSteps/Root`）。"""
    if program is None:
        raise SpecError(f"{where}: `Program` 是 null")
    want_fields(program, {"Id", "MaxNodeDepth", "MaxProgramSteps", "Root"}, where + ".Program")
    return {
        "id": str(unwrap(optional(program, "Id", {"Value": "(unnamed)"}))),
        "depth": int(optional(program, "MaxNodeDepth", 64)),
        "steps": int(optional(program, "MaxProgramSteps", 1024)),
        "root": node(get(program, "Root", where), where + ".Program.Root"),
    }


# `CARD` 行的全部字段（实测 62 张卡的并集；`FLAG_WRAP_LOWER` 的 Id/Tags 都在其中）。
# `IsAction` / `QueueOnPlay` / `PlayCondition` 本内容 62/62 都缺位 —— 缺位就是 false/null，
# 但字段表里留着它们，因为"这张表里能出现什么"是格式的事实，不是这份内容的巧合。
CARD_FIELDS_ALLOWED = {"Id", "PackageId", "Costs", "Tags", "Program", "LifecyclePrograms",
                       "PlayedCardDestinationZone", "TurnEndHandDestinationZone", "RetainInHandOnTurnEnd",
                       "IsAction", "QueueOnPlay", "PlayCondition"}


def card_spec(rom, index, rec):
    card_id = rec.get("Id")
    if card_id is None:
        raise SpecError(f"CARD[{index}] 没有 Id")
    where = f"card({card_id})"
    want_fields(rec, CARD_FIELDS_ALLOWED, where)

    tags = optional(rec, "Tags", [])
    for tag in tags:
        if not isinstance(unwrap(tag), str):
            raise SpecError(f"{where}: Tags 里出现了非字符串 {tag!r}")

    costs = []
    for position, cost in enumerate(optional(rec, "Costs", [])):
        cwhere = f"{where}.Costs[{position}]"
        costs.append({
            "resource": str(unwrap(get(cost, "ResourceId", cwhere))),
            "amount": int(get(cost, "Amount", cwhere)),
        })

    if optional(rec, "PlayCondition", None) is not None:
        raise SpecError(f"{where}: `PlayCondition` 非空，本轮的 authoring 不支持它")
    lifecycle = optional(rec, "LifecyclePrograms", {}) or {}
    if lifecycle:
        raise SpecError(f"{where}: `LifecyclePrograms` 非空（{sorted(lifecycle)}），本轮的 authoring 不支持它")

    program = get(rec, "Program", where)
    if program is None:
        raise SpecError(f"{where}: `Program` 是 null —— 本轮不做无程序卡（镜像里有的话，先想清楚它算什么）")

    return {
        "index": index,
        "id": str(unwrap(card_id)),
        "package": optional(rec, "PackageId", "scenario"),
        "costs": costs,
        "tags": [str(unwrap(tag)) for tag in tags],
        "played_zone": enum_of(rec, "PlayedCardDestinationZone", CARD_ZONES, where)
                       if "PlayedCardDestinationZone" in rec else "DiscardPile",
        "turn_end_zone": enum_of(rec, "TurnEndHandDestinationZone", CARD_ZONES, where)
                         if "TurnEndHandDestinationZone" in rec else "DiscardPile",
        "retain": bool(optional(rec, "RetainInHandOnTurnEnd", False)),
        "is_action": bool(optional(rec, "IsAction", False)),
        "queue_on_play": bool(optional(rec, "QueueOnPlay", False)),
        "lifecycle": len(lifecycle),
        "play_condition": None if optional(rec, "PlayCondition", None) is None else "set",
        "program": program_spec(program, where),
    }


def derive(rom):
    """镜像 → 规范描述（纯函数：不碰磁盘）。`fight_diff.py` 用它核对磁盘上的文件是否陈旧。"""
    cards = [card_spec(rom, index, rec) for index, rec in enumerate(rom._rows("CARD"))]

    # 卡程序引用到的状态（含触发器程序里引用的）。触发器自己引用的状态也要递归进来 ——
    # 否则 authoring 会在注册表编译时报"未知状态"，而报错点离真正的原因很远。
    card_statuses = status_closure(rom, [card["program"]["root"] for card in cards], "status")

    actions = enemy_actions(rom)

    used_by = {status_id: ["cards"] for status_id in card_statuses}
    for action in actions:
        for status_id in action["statuses"]:
            used_by.setdefault(status_id, []).append("enemy_actions")
    statuses = []
    for status_id in sorted(used_by):
        spec = card_statuses.get(status_id) or status_spec(rom, status_id, "status")
        spec["used_by"] = sorted(set(used_by[status_id]))
        statuses.append(spec)

    # 被 createCardInstance 造出来的卡 id 必须是镜像里真有的卡 —— 否则 C# authoring 会静默少一张定义。
    known = {card["id"] for card in cards}
    for card in cards:
        created = []
        _created_cards(card["program"]["root"], created)
        for card_id in created:
            if card_id not in known:
                raise SpecError(
                    f"card({card['id']}): createCardInstance 指向镜像里不存在的卡 `{card_id}`")

    return {
        "format": SPEC_FORMAT,
        "image": IMAGE_REL.replace("\\", "/"),
        "image_bytes": os.path.getsize(IMAGE),
        "card_count": len(cards),
        "enemy_action_count": len(actions),
        "statuses": statuses,
        "cards": cards,
        "enemy_actions": actions,
    }


def render(spec):
    return json.dumps(spec, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def load_rom():
    import reader  # noqa: E402  (sys.path 要先就位)
    with open(IMAGE, "rb") as handle:
        return reader.Rom(handle.read())


def main(argv):
    check = "--check" in argv
    rom = load_rom()
    spec = derive(rom)
    text = render(spec)

    if check:
        if not os.path.isfile(OUT):
            raise SpecError(f"{OUT} 不存在。生成命令：python native/gen_card_specs.py")
        with open(OUT, "r", encoding="utf-8", newline="") as handle:
            on_disk = handle.read()
        if on_disk != text:
            raise SpecError(
                f"{OUT} 与镜像不一致（陈旧产物）。镜像变了就要重生成：\n"
                f"    python native/gen_card_specs.py")
        print("card_specs.json 与镜像一致（%d 卡 / %d 状态 / %d B）"
              % (spec["card_count"], len(spec["statuses"]), len(text.encode("utf-8"))))
        return 0

    with open(OUT, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("wrote %s (%d B): %d cards, %d statuses"
          % (OUT, len(text.encode("utf-8")), spec["card_count"], len(spec["statuses"])))
    for status in spec["statuses"]:
        print("  status %-12s polarity=%-8s stacking=%-24s tags=%s modifiers=%d triggers=%d"
              % (status["id"], status["polarity"], status["stacking"], status["tags"],
                 len(status["passive_modifiers"]), len(status["triggers"])))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SpecError as failure:
        print("SPEC FAIL", file=sys.stderr)
        print(str(failure), file=sys.stderr)
        sys.exit(1)
