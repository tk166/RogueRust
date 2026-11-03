"""§194 helpers: the JSON constructors for boss content (same shapes `patch_175_act3.py` set)."""


def sel(kind, capability=None, extra=None):
    value = extra if extra is not None else {
        "Cardinality": "ZeroOrOne",
        "RequiredContextCapabilities": capability,
    }
    return {"kind": kind, "value": value}


def source():
    return sel("sel.source", "Source")


def hero():
    return sel("sel.eventTarget", "EventTarget")


def allies():
    """`sel.allAllies` -- "all enemies" **from the boss's side**.

    `sel.allEnemies` is the *opposing* team (`targets::team_set(state, source, false, ..)`), so
    Donu's "all enemies gain 3 Strength" has to be spelled `allAllies`; using `allEnemies` there
    would buff the player.
    """
    return sel("sel.allAllies", extra={"Cardinality": "All", "RequiredContextCapabilities": "Source"})


def program(children):
    if len(children) == 1:
        root = children[0]
    else:
        root = {"kind": "node.sequence", "value": {"Children": children}}
    return {"Id": {"Value": "(unnamed)"}, "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def const(value):
    return {"kind": "const", "value": {"Value": value}}


def _expr(value):
    """Wrap a bare int as a `const` node.

    Every child of an arithmetic node is a **term**, not a number: `divide.Right` written as `12`
    gives that field the storage class `int` instead of `term`, the deriver sees a mixed shape and
    falls back to `F_JSON`, and the kernel's `eval_int` then fails with `WrongKind("F_JSON")` -- a
    failure three layers away from the missing `const` (the build report's "Fields that fell back to
    F_JSON" line is the only place it shows up at authoring time).
    """
    return value if isinstance(value, dict) else const(value)


def add(left, right):
    return {"kind": "add", "value": {"Left": _expr(left), "Right": _expr(right)}}


def subtract(left, right):
    return {"kind": "subtract", "value": {"Left": _expr(left), "Right": _expr(right)}}


def divide(left, right):
    return {"kind": "divide", "value": {"Left": _expr(left), "Right": _expr(right)}}


def maximum(left, right):
    return {"kind": "max", "value": {"Left": _expr(left), "Right": _expr(right)}}


def current_health(target):
    return {"kind": "currentHealth", "value": {"Selector": target}}


def max_health(target):
    return {"kind": "maxHealth", "value": {"Selector": target}}


def stacks_of(status_id, target=None):
    return {
        "kind": "combatantStatusStacks",
        "value": {"Selector": target or source(), "StatusId": {"value": status_id}},
    }


def counter_of(name):
    return {"kind": "combatantCounter", "value": {"Selector": source(), "CounterId": name}}


def hit(amount, target=None):
    return {
        "kind": "node.dealDamage",
        "value": {
            "TargetSelector": target or hero(),
            "Amount": amount if isinstance(amount, dict) else const(amount),
            "ResultKey": None,
            "IgnoresBlock": False,
            "Element": None,
        },
    }


def block(amount, target=None):
    return {
        "kind": "node.gainBlock",
        "value": {
            "TargetSelector": target or source(),
            "Amount": amount if isinstance(amount, dict) else const(amount),
            "ResultKey": None,
        },
    }


def heal(amount, target=None):
    return {
        "kind": "node.heal",
        "value": {
            "TargetSelector": target or source(),
            "Amount": amount if isinstance(amount, dict) else const(amount),
            "ResultKey": None,
        },
    }


def status(status_id, n, target="event"):
    if target == "event":
        who = hero()
    elif isinstance(target, dict):
        who = target
    else:
        who = source()
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": who,
            "StatusDefinitionId": {"value": status_id},
            "Stacks": n if isinstance(n, dict) else const(n),
            "DurationTurns": 0,
            "Charges": 0,
            "ResultKey": None,
        },
    }


def drop_status(status_id, target=None):
    """Removal is `modifyStatusStacks` with a huge negative delta (§175's established trick)."""
    return {
        "kind": "node.modifyStatusStacks",
        "value": {
            "TargetSelector": target or source(),
            "StatusDefinitionId": {"value": status_id},
            "Delta": const(-99),
        },
    }


def set_counter(name, value, relative=False):
    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": source(),
            "CounterId": {"value": name},
            "Amount": const(value),
            "Relative": relative,
            "ResultKey": None,
        },
    }


def card_to_discard(card_id, count):
    return {
        "kind": "node.createCardInstance",
        "value": {
            "CardDefinitionId": {"value": card_id},
            "Count": count if isinstance(count, dict) else const(count),
            "TargetSelector": hero(),
            "ToZone": "DiscardPile",
            "ResultKey": None,
        },
    }


def repeat(count, body):
    return {"kind": "node.repeat", "value": {"Count": count, "Body": body}}


def conditional(condition, then, otherwise=None):
    return {"kind": "node.conditional", "value": {"Condition": condition, "Then": then, "Else": otherwise}}


def compare(op, left, right):
    return {"kind": "compare", "value": {"Op": op, "Left": left, "Right": right}}


def c_all(conditions):
    return {"kind": "intent.allOf", "value": {"Conditions": conditions}}


def c_any(conditions):
    return {"kind": "intent.anyOf", "value": {"Conditions": conditions}}


def c_health(op, percent):
    return {"kind": "intent.healthPercent", "value": {"Op": op, "Percent": percent}}


def c_round(op, n):
    return {"kind": "intent.round", "value": {"Op": op, "Round": n}}


def c_rounds(values):
    return c_any([c_round("Equal", value) for value in values])


def c_counter(name, op, value):
    # ⚠️ `Counter` is the **wrapped** spelling (`{"value": name}`), like every other id in this
    # document. A plain string here makes the derived field kind differ from the existing rows
    # (`sentry.bolt`, `cultist.incarnation`), the deriver then picks `F_TERM` for the whole shape and
    # the kernel's `str_field("Counter")` fails with `WrongKind("F_TERM")` -- which shows up as
    # "a summoned minion has no intent", three layers away from the typo.
    return {"kind": "intent.selfHasCounter",
            "value": {"Counter": {"value": name}, "Op": op, "Value": value}}


def c_asc(n):
    return {"kind": "intent.ascensionAtLeast", "value": {"Value": n}}


def rule(condition, action_id, priority):
    return {"Condition": condition, "Action": {"value": action_id}, "Priority": priority}


def action(action_id, name, label, intent, children, variants=()):
    record = {
        "Id": action_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": label,
        "Intent": {"Kind": intent, "Label": label},
        "Program": program(children),
    }
    if variants:
        record["ProgramAsc"] = [
            {"AscensionMin": threshold, "Program": program(build())} for threshold, build in variants
        ]
    return record
