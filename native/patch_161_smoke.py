"""smoke.mjs: the eight new exports go on the hand-kept REQUIRED list.

`REQUIRED` is the direction that catches "the ABI lost a symbol the page needs"; the reverse
direction (the page calls only real exports) is derived, so it needs nothing here.
"""
import io

PATH = "web/smoke.mjs"

ANCHOR = """  "rd_env_card_kind", "rd_run_card_kind", "rd_run_node_resolved", "rd_run_boss_beaten","""

NEW = """  "rd_env_card_kind", "rd_run_card_kind", "rd_run_node_resolved", "rd_run_boss_beaten",
  // §161.3: the pending card choice (Elixir / Gambler's Brew). The options are zone `3` of the
  // pile exports above, so there is no second set of string getters to keep in sync.
  "rd_env_choice_pending", "rd_env_choice_kind", "rd_env_choice_min", "rd_env_choice_max",
  "rd_env_choice_count", "rd_env_choice_pick", "rd_env_choice_selected", "rd_env_choice_clear",
  "rd_env_choice_confirm","""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "rd_env_choice_pending" not in text, "already inserted"
    text = text.replace(ANCHOR, NEW)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("smoke.mjs: REQUIRED widened")


if __name__ == "__main__":
    main()
