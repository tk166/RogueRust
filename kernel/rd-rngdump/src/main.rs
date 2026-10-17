//! Dumps shuffle sequences for the differential test.
//!
//! Reads a case file of `count seed step` lines, writes one `count seed step i0 i1 ... iN-1`
//! line per case. The Python driver runs the same cases through the NativeAOT build of the real
//! C# engine and diffs the two - which is the whole conformance mechanism, exercised on its
//! smallest possible surface before the rest of the kernel depends on it.

use std::env;
use std::fs;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: rd-rngdump <cases.txt> <out.txt>");
        return ExitCode::from(2);
    }

    let input = match fs::read_to_string(&args[1]) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("cannot read {}: {e}", args[1]);
            return ExitCode::from(2);
        }
    };

    let mut cases = 0usize;
    let mut out = String::new();

    for (lineno, raw) in input.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() != 3 {
            eprintln!("line {}: expected 'count seed step', got {line:?}", lineno + 1);
            return ExitCode::from(2);
        }
        let count: usize = match parts[0].parse() {
            Ok(v) => v,
            Err(_) => {
                eprintln!("line {}: bad count", lineno + 1);
                return ExitCode::from(2);
            }
        };
        let seed: i32 = parts[1].parse().unwrap_or(0);
        let step: i32 = parts[2].parse().unwrap_or(0);

        // The kernel is allocator-free by design, but this harness runs on the host and needs
        // a buffer sized at runtime. That is a property of the harness, not of the kernel.
        if count > 255 {
            eprintln!("line {}: count {count} exceeds the u8 index bound", lineno + 1);
            return ExitCode::from(2);
        }
        let mut buf = vec![0u8; count];
        rd_core::rng::shuffle_indexes(&mut buf, seed, step);

        out.push_str(&format!("{count} {seed} {step}"));
        for v in &buf {
            out.push_str(&format!(" {v}"));
        }
        out.push('\n');
        cases += 1;
    }

    if let Err(e) = fs::write(&args[2], out) {
        eprintln!("cannot write {}: {e}", args[2]);
        return ExitCode::from(2);
    }
    println!("rd-rngdump: wrote {cases} cases to {}", args[2]);
    ExitCode::SUCCESS
}
