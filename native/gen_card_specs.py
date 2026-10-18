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
SPEC_FORMAT = 1

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

SELECTORS = {"sel.eventTarget": "eventTarget", "sel.source": "source", "sel.allEnemies": "allEnemies"}
SELECTOR_FIELDS = {"Cardinality", "RequiredContextCapabilities"}

# 每种节点**允许**出现的字段。镜像省略与默认值相等的键，所以可选字段在这里是"允许但不要求"。
NODE_FIELDS = {
    "node.noop": set(),
    "node.sequence": {"Children"},
    "node.dealDamage": {"Amount", "Element", "IgnoresBlock", "Kind", "ResultKey", "TargetSelector"},
    "node.applyStatus": {"Charges", "DurationTurns", "ResultKey", "SourceSelector", "Stacks",
                         "StatusDefinitionId", "TargetSelector", "UnrefusableBy"},
    "node.gainBlock": {"Amount", "ResultKey", "TargetSelector"},
    "node.drawCards": {"Count", "ResultKey", "TargetSelector"},
    "node.gainResource": {"Amount", "DefaultMax", "ResourceId", "ResultKey", "TargetSelector"},
    "node.createCardInstance": {"CardDefinitionId", "Count", "ResultKey", "TargetSelector", "ToZone"},
    "node.forEachCardInZone": {"Body", "DefinitionFilter", "MaxIterations", "OwnerSelector",
                               "TagFilter", "TakeFirst", "Zone"},
    "node.moveCardToZone": {"CardExpression", "OwnerSelector", "Placement", "ResultKey", "ToZone"},
    "node.modifyStatusStacks": {"Children", "Delta", "ResultKey", "StatusDefinitionId", "TargetSelector"},
}
EXPRESSION_FIELDS = {
    "const": {"Value"},
    "multiply": {"Left", "Right"},
    "combatantStatusStacks": {"Selector", "StatusId"},
}
CARD_EXPRESSION_FIELDS = {"cardInstance.iterated": set()}

# 镜像里每个选择器都带 `Cardinality` / `RequiredContextCapabilities` 两格。
# 它们不是"我们授权的参数"，而是这三种选择器在参考实现里的固定属性
# （`CombatantTargetSelectors.cs:77/115/154`：Source/EventTarget 都是 ZeroOrOne），
# 所以这里**钉住**它们：换成一个别的选择器混进来，闸门要立刻砸下来。
SELECTOR_CAPABILITIES = {
    "eventTarget": ("ZeroOrOne", "EventTarget"),
    "source": ("ZeroOrOne", "Source"),
    "allEnemies": ("ZeroOrOne", "AllEnemiesOfSource"),
}

DAMAGE_KINDS = {"Direct", "DamageOverTime"}
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
    if kind == "multiply":
        return {"kind": "multiply",
                "left": expression(get(body, "Left", where), where + ".Left"),
                "right": expression(get(body, "Right", where), where + ".Right")}
    if kind == "combatantStatusStacks":
        return {"kind": "combatantStatusStacks",
                "selector": selector(get(body, "Selector", where), where + ".Selector"),
                "status": str(unwrap(get(body, "StatusId", where)))}
    raise SpecError(f"{where}: 不认识的表达式 `{kind}`")


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
    want_fields(body, allowed, f"{where}({kind})", allow_empty_children=kind != "node.sequence")

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
    if kind == "multiply":
        return "multiply(%s,%s)" % (expression_text(value["left"]), expression_text(value["right"]))
    if kind == "combatantStatusStacks":
        return "combatantStatusStacks(selector=%s;status=%s)" % (
            selector_text(value["selector"]), value["status"])
    if kind == "iterated":
        return "iterated"
    raise SpecError("expression_text: 不认识 %r" % (kind,))


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
    wanted = []
    queue = []
    for card in cards:
        _status_refs(card["program"]["root"], queue)
    while queue:
        status_id = queue.pop()
        if status_id in wanted:
            continue
        wanted.append(status_id)
        spec = status_spec(rom, status_id, "status")
        for trigger in spec["triggers"]:
            _status_refs(trigger["program"]["root"], queue)

    statuses = [status_spec(rom, status_id, "status") for status_id in sorted(wanted)]

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
        "statuses": statuses,
        "cards": cards,
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
