"""Find where the brace depth of `run.rs` goes wrong (my splice left one extra `}`)."""
import io

PATH = "kernel/rd-wasm/src/run.rs"
BACKSLASH = chr(92)
QUOTE = chr(34)


def strip(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == QUOTE:
            i += 1
            while i < n and text[i] != QUOTE:
                if text[i] == BACKSLASH:
                    i += 1
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != chr(10):
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def main():
    text = io.open(PATH, encoding="utf-8").read()
    code = strip(text)
    depth = 0
    line = 1
    for ch in code:
        if ch == chr(10):
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                print("depth went negative at line", line)
                print(repr(text.split(chr(10))[line - 1]))
                return
    print("final depth", depth)


if __name__ == "__main__":
    main()
