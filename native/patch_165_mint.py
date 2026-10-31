"""§161.5 rd-core: one place that turns a counter into `card_%06d`.

`exec.rs` has done this since §88 (`create_card_for`); `Offered` needs it from `state.rs`. Two
minting paths would mean two ideas about "which number is next", so the formatting + the counter
bump move here and `exec.rs` calls them.
"""
import io

PATH = "kernel/rd-core/src/state.rs"

ANCHOR = """    /// 把每副本价格写到**那一份副本**上（[`CARD_COST_DELTA_COUNTER`]）。"""

MINTING = '''    /// 铸一张**新卡**：取号 → 建实例 → 按底插入牌区。返回它的池槽位。
    ///
    /// 参考 `CombatState.CreateNextCardInstanceId`（`CombatState.cs:689-696`）：
    /// `$"card_{NextCardInstanceNumber:000000}"`，**先取号再自增**（`exec.rs` 那条
    /// `next_card_instance_number == 1` 的测试就是钉这个的）。
    ///
    /// §161.5 把铸号从 `exec.rs` 搬到这里：发号器是 `CombatState` 的字段，铸号也该在同一个模块。
    /// 两条铸号路径会给出两个"下一个是几"，而那是一种最难看的错 —— 每条路径单独看都对。
    pub fn create_card_instance(
        &mut self,
        owner: &CombatantId,
        definition: CardDefinitionId,
        zone: CardZone,
    ) -> StateResult<CardSlot> {
        let number = self.next_card_instance_number;
        let mut buffer = [0u8; INSTANCE_TEXT_CAP];
        // 装不下是**不可能**的（`INSTANCE_TEXT_CAP` 是 32，最长情形 17）；真发生时返回 `None`
        // 而不是截断 —— 一个被截断的 id 会和另一张牌撞名。
        let text = numbered_text(b"card_", number, &mut buffer)
            .ok_or(CapacityError::IdNotAscii)?;
        let id = CardInstanceId::new(text)?;
        let slot = self.push_card(owner, zone, CardInstance::new(id, definition))?;
        self.next_card_instance_number = number.saturating_add(1);
        Ok(slot)
    }

    /// 把每副本价格写到**那一份副本**上（[`CARD_COST_DELTA_COUNTER`]）。'''

NUMBERED = '''
/// 装一个 `<prefix>%06d` 的栈上缓冲要多大。
///
/// 最长情形：`status_`(7) + `i32` 的 10 位十进制 = 17 B。取 32 是"怎么都不会撞上"的余量，
/// 真正越界时 [`numbered_text`] 返回 `None` 而不是截断。
pub const INSTANCE_TEXT_CAP: usize = 32;

/// `<prefix>%06d` 的**零分配**版（`format!` 在 `no_std` 里没有）。
///
/// 逐字对应 C# 的 `$"{prefix}{number:000000}"`：负数在参考里不可能出现（生成器从 1 开始），
/// 真出现时按 **0** 写（与旧实现一致，那不是"猜"，是"不可能发生"）。
/// 返回的 `&str` 借用 `buffer`，所以调用方持有它、并立刻用完。
///
/// §161.5：从 `exec.rs` 搬到这里（`create_card_instance` 在这里用它）。`exec.rs` 的
/// `status_%06d` 与 `summoned_%06d` 也读这一份 —— 一处实现，三处读。
#[must_use]
pub fn numbered_text<'b>(
    prefix: &[u8],
    number: i32,
    buffer: &'b mut [u8; INSTANCE_TEXT_CAP],
) -> Option<&'b str> {
    // 10 位十进制够装下 `u32::MAX`（10 位），再补前导 0 到 6 位。
    let mut digits = [b'0'; 12];
    let mut len = 0usize;
    let mut value = if number < 0 { 0u32 } else { number as u32 };
    loop {
        let slot = digits.get_mut(len)?;
        *slot = b'0' + (value % 10) as u8;
        len += 1;
        value /= 10;
        if value == 0 {
            break;
        }
    }
    while len < 6 {
        let slot = digits.get_mut(len)?;
        *slot = b'0';
        len += 1;
    }
    let head = buffer.get_mut(..prefix.len())?;
    head.copy_from_slice(prefix);
    for index in 0..len {
        let slot = buffer.get_mut(prefix.len() + index)?;
        // 反着写：`digits` 是低位在前。
        *slot = digits[len - 1 - index];
    }
    core::str::from_utf8(&buffer[..prefix.len() + len]).ok()
}

'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert "fn create_card_instance" not in text, "already inserted"
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    text = text.replace(ANCHOR, MINTING)

    # the free function goes next to `StateResult` (module level, after the type aliases)
    anchor2 = """/// Element of a fixed-capacity container: supplies the value of a vacant slot, so containers can
/// be built without an allocator (and, later, in `static` storage)."""
    assert text.count(anchor2) == 1, text.count(anchor2)
    text = text.replace(anchor2, NUMBERED.lstrip("\n") + anchor2)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: create_card_instance + numbered_text")


if __name__ == "__main__":
    main()
