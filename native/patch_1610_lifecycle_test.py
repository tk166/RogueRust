"""§161.10: the archive capacity test also pins the **fight lifecycle** guard.

The review's completion criterion: "即使绕过 UI，战斗中仍无法完成不合法的存档／回档". These
assertions call the ABI directly, so the page's `mode` check cannot be what makes them pass.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

OLD = """        // …and **one byte past the capacity** is refused, not clamped."""

NEW = """        // §161.10: **bypass the UI and call the ABI** -- a fight must refuse both directions.
        assert_eq!(rd_run_fight_begin(), 0, "begin a fight");
        assert_eq!(
            rd_run_archive_fill(),
            -2,
            "archiving mid-fight must be refused by the ABI, not only by the page"
        );
        let buf = rd_run_archive_buf();
        assert_eq!(
            unsafe { rd_run_restore_from(buf, big) },
            -2,
            "restoring mid-fight must be refused by the ABI too"
        );

        // …and **one byte past the capacity** is refused, not clamped."""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("lifecycle assertions added (ABI level, no page involved)")


if __name__ == "__main__":
    main()
