/* link.x —— 只为回答两个问题，**不是一个可启动的固件**。
 *
 * 它回答的是：
 *   1. 这个内核**能不能被链接成一个完整的镜像**？裸机移植最常见的死法不是编译不过，
 *      而是链接时缺符号 —— `memcpy` / `memset` / `__aeabi_*` 这类编译器内建函数在
 *      `cargo check` 里永远看不见，只有真链接才会暴露。这正是本项目此前一直没验证的一件事。
 *   2. `--gc-sections` 之后**真实保留**了多少？静态库里躺着的东西（`core`、
 *      `compiler_builtins` 的几百个目标文件）不等于最终镜像里的东西，只有链接才知道。
 *
 * ⚠️ **它不是能烧进 ESP32-P4 的镜像**，理由写清楚，免得后人误用：
 *   * 没有真实的内存映射。ESP32-P4 的 HP L2MEM / TCM / LP SRAM 基地址需要从 TRM 取，
 *     我没有可靠来源，所以这里**故意用 0 占位**，而不是编一个看起来像真的地址。
 *     段尺寸与地址无关，所以这不影响上面两个问题的答案。
 *   * 没有 bootloader 头、没有 `_start` 之外的启动代码（时钟/SP/向量表/PSRAM 初始化都没有）。
 *   * 没有把 `.data` 从 flash 拷进 RAM 的启动代码 —— 那段必须由启动代码做。
 *
 * 上板前必须替换的东西，按重要性：真实 MEMORY 映射 → 启动代码 → 链接器脚本的
 * `ENTRY` 与段布局 → bootloader 头。这是 W4 余下的工作。
 */

ENTRY(_start)

SECTIONS
{
  /* 0 是刻意的占位符，不是地址。见文件头的警告。 */
  . = 0x00000000;

  .text : ALIGN(4)
  {
    *(.text .text.*)
    *(.init .init.*)
  }

  .rodata : ALIGN(4)
  {
    *(.rodata .rodata.*)
    *(.srodata .srodata.*)
  }

  /* 真正会占 RAM 的两段。`.data` 的初值在 flash，运行时被拷进 RAM；
   * `.bss` 不占 flash，只占 RAM。这两笔账必须分开，别相加（见 tools/size_probe.py）。 */
  .data : ALIGN(4)
  {
    *(.data .data.*)
    *(.sdata .sdata.*)
  }

  .bss (NOLOAD) : ALIGN(4)
  {
    *(.bss .bss.*)
    *(.sbss .sbss.*)
    *(COMMON)
  }

  /DISCARD/ :
  {
    *(.eh_frame)
    *(.eh_frame_hdr)
    *(.comment)
    *(.note .note.*)
    *(.riscv.attributes)
  }
}
