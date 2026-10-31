"""web/index.html: the picker's sentence now comes from (source, kind).

`kind` alone could not tell "from your discard pile" from "from three random attack cards" -- both
are `ToHand`. The first version wrote the discard-pile sentence for an Attack Potion.
"""
import io

PATH = "web/index.html"


def main():
    text = io.open(PATH, encoding="utf-8").read()

    old = """  const titles = {
    1: "消耗任意张手牌",
    2: "弃掉任意张手牌，然后抽同样多张",
    3: "从弃牌堆拿一张回手牌（它这次免费）",
  };"""
    new = """  // §161.5: the sentence is a function of **both** halves. `kind` alone cannot tell "from your
  // discard pile" from "from three random attack cards" -- they are the same `then`.
  const source = ex.rd_env_choice_source();
  const titles = {
    "1:1": "消耗任意张手牌",
    "1:2": "弃掉任意张手牌，然后抽同样多张",
    "1:3": "从弃牌堆拿一张回手牌（它这次免费）",
    "2:3": "从三张候选里选一张加进手牌（它这次免费）",
  };"""
    assert text.count(old) == 1, text.count(old)
    text = text.replace(old, new)

    old2 = """  document.getElementById("modalTitle").textContent = `${titles[kind] || "选牌"} · ${span}`;"""
    new2 = """  document.getElementById("modalTitle").textContent =
    `${titles[source + ":" + kind] || "选牌"} · ${span}`;"""
    assert text.count(old2) == 1, text.count(old2)
    text = text.replace(old2, new2)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("picker: sentence from (source, kind)")


if __name__ == "__main__":
    main()
