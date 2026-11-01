"""§163.2 fix: the `log(...)` lines landed inside the `let … else { … };` binding.

`run_slot()` appears on the binding's first line, and the `else` body follows it — so "insert after
the line that mentions run_slot()" put the log between `else {` and `return -1;`. It has to go after
the closing `};` of that binding.
"""
import io
import re

PATH = "kernel/rd-wasm/src/run.rs"


def main():
    text = io.open(PATH, encoding="utf-8").read()
    # every misplaced line looks like: `    else {\n    session.log(...);\n        return -1;\n    };`
    pattern = re.compile(
        r"\n(    let Some\(session\) = run_slot\(\)[^\n]*else \{)\n(    session\.log\([^\n]*\);\n)((?:[^\n]*\n)*?    \};)"
    )
    fixed, count = pattern.subn(lambda m: "\n" + m.group(1) + "\n" + m.group(3) + "\n" + m.group(2).rstrip("\n"), text)
    assert count >= 10, count
    io.open(PATH, "w", encoding="utf-8", newline="").write(fixed)
    print(f"moved {count} log lines after their bindings")


if __name__ == "__main__":
    main()
