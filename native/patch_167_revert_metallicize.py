"""Revert the metallicize trigger: it is a **host step**, not a content trigger.

`host.rs:1192` pays `standard.metallicize` (and `standard.plated_armor`) at turn end -- ported from
the reference, where Metallicize is a `TurnEndedHandler` rather than a declarative trigger
(`port-plan.md` §112). `standard.metallicize`'s `Triggers: null` is therefore **correct**: the
status does nothing *declaratively* because the kernel does it.

I added a trigger here after reading "`Triggers: null` ⇒ a decorative status", which is the wrong
inference: it is decorative only if no host step claims it. Two tests caught the double payment
(`metallicize_grants_block_at_the_end_of_the_turn`,
`plated_armor_and_metallicize_both_pay_block_at_turn_end`) -- which is what they are for.
"""
import io
import json

PACKAGE = "tools/contentc/packages/sts/sts.roguedeck.json"
CHECK = "native/sts_content_check.py"


def main():
    doc = json.loads(io.open(PACKAGE, encoding="utf-8").read())
    for status in doc["Statuses"]:
        if status["Id"] == "standard.metallicize":
            assert status.get("Triggers") is not None, "nothing to revert"
            status["Triggers"] = None
            break
    else:
        raise SystemExit("standard.metallicize not found")
    io.open(PACKAGE, "w", encoding="utf-8", newline="").write(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    )

    check = io.open(CHECK, encoding="utf-8").read()
    old = '''                     "standard.time_warp", "standard.constricted",
                     # §161.7: a power status with a turn-end trigger.
                     "standard.metallicize"):'''
    new = '''                     "standard.time_warp", "standard.constricted"):'''
    assert check.count(old) == 1, check.count(old)
    check = check.replace(old, new)
    old2 = '''                        "standard.constricted": ["TurnEnded"],
                        # §161.7: Metallicize is a *power* -- "at the end of your turn, gain
                        # 3(4) Block". Its status had no trigger at all, i.e. `Heart of Iron`
                        # has been handing out a decorative buff since §158.
                        "standard.metallicize": ["TurnEnded"]}[sid]'''
    new2 = '''                        "standard.constricted": ["TurnEnded"]}[sid]'''
    assert check.count(old2) == 1, check.count(old2)
    check = check.replace(old2, new2)
    io.open(CHECK, "w", encoding="utf-8", newline="").write(check)
    print("metallicize trigger reverted (the kernel pays it)")
    # and say so where the fact lives
    print("NOTE: the status's Triggers must stay null -- host.rs pays it as a turn-end step.")


if __name__ == "__main__":
    main()
