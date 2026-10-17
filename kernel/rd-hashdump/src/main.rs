//! Hashes a list of files with the kernel's own SHA-256.
//!
//! The point is to close the loop on the fingerprint half of the conformance story BEFORE the
//! state model exists: the C# engine can hand over the canonical text it hashes
//! (`rd_oracle_hash_input_*`), so "does the ported hasher agree with the original on real
//! engine text?" can be answered today. NIST vectors alone prove nothing about the engine's
//! own output.
//!
//! Reads a list file (one path per line), writes `path hex` per line.

// The kernel's hasher, included BY PATH rather than depended on. Same file on disk, so it
// cannot drift from what rd-core ships; no `rd-core` dependency, so this tool keeps working
// while the rest of the kernel is mid-edit and momentarily does not compile.
#[path = "../../rd-core/src/hash.rs"]
mod hash;

use std::env;
use std::fs;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: rd-hashdump <list.txt> <out.txt>");
        return ExitCode::from(2);
    }

    let list = match fs::read_to_string(&args[1]) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("cannot read {}: {e}", args[1]);
            return ExitCode::from(2);
        }
    };

    let mut out = String::new();
    let mut n = 0usize;
    for line in list.lines() {
        let path = line.trim();
        if path.is_empty() {
            continue;
        }
        // Read as BYTES: the canonical text's exact bytes are the whole point, so no newline
        // translation and no encoding guessing.
        let data = match fs::read(path) {
            Ok(d) => d,
            Err(e) => {
                eprintln!("cannot read {path}: {e}");
                return ExitCode::from(2);
            }
        };
        let digest = hash::sha256(&data);
        let mut hex = [0u8; 64];
        hash::to_hex_lower(&mut hex, &digest);
        out.push_str(path);
        out.push(' ');
        out.push_str(std::str::from_utf8(&hex).unwrap_or(""));
        out.push('\n');
        n += 1;
    }

    if let Err(e) = fs::write(&args[2], out) {
        eprintln!("cannot write {}: {e}", args[2]);
        return ExitCode::from(2);
    }
    println!("rd-hashdump: hashed {n} file(s)");
    ExitCode::SUCCESS
}

/// Keeps the module's own tests reachable from `cargo test -p rd-hashdump`, so the NIST
/// vectors travel with the file that is being included.
#[cfg(test)]
mod hash_tests {
    use super::hash;

    #[test]
    fn included_hasher_still_matches_nist() {
        let mut hex = [0u8; 64];
        hash::to_hex_lower(&mut hex, &hash::sha256(b"abc"));
        assert_eq!(
            std::str::from_utf8(&hex).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
