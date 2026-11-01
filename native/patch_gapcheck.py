"""Fix the mangled regex in gap_check.py: a `\\b` written through a patch string became a literal
backspace (0x08), so the pattern could never match and the script reported "0 consulted" -- a metric
lying in the direction of "we do less than we do".

Uses no escapes at all: counting the constructor name as a plain substring is enough here, and it
cannot be silently corrupted.
"""
import io
import re

PATH = "native/gap_check.py"


def main():
    text = io.open(PATH, encoding="utf-8").read()
    # Drop any stray control characters a previous patch left behind.
    cleaned = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if cleaned != text:
        print("removed", len(text) - len(cleaned), "control character(s)")
    pattern = re.compile(r"^ *mentions = len\(re\.findall\(.*$", re.M)
    assert len(pattern.findall(cleaned)) == 1, len(pattern.findall(cleaned))
    cleaned = pattern.sub(
        "        mentions = kernel.count(chr(65) + chr(95) + name)  # 'A_' + name, no escapes", cleaned)
    io.open(PATH, "w", encoding="utf-8", newline="").write(cleaned)
    print("occurrence counting rewritten without escapes")


if __name__ == "__main__":
    main()
