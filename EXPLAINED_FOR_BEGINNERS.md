# Jane Street ASIC Puzzle 2026 — Reading a Chip From Its Layout, Explained for Beginners

This is a beginner explainer for this project, in plain language with one simple analogy. It is not a replacement for the technical paper or report.

**How to read the honesty labels:**

- **Verified** = the number or result is in a file Jayant actually produced, and it was checked here.
- **Reported, not verified** = the number comes from Jayant's own summary or slides. No seeds, no confidence intervals, and no test code were given with it. Treat it as "he says so", not "proven".
- **Plan only** = an idea or a target. It has not happened yet.

---


**In one line:** Jayant reverse-engineered a computer chip from its physical layout alone, and found the secret key that makes it say the flag.

**Analogy:** Imagine being given only a photo of a locked safe's insides, with no manual. You trace every wire, rebuild the lock in your head, and work out the combination.

**What Jayant actually did (verified):**

- The puzzle gave only a chip layout file, called a GDS file. No source code, no manual.
- He extracted the circuit from the layout. The chip had 728 working cells: 636 simple gates and 92 flip-flops.
- He checked his tools on a smaller warmup chip first. That warmup check passed exactly.
- He checked his extracted chip against the example waveform given with the puzzle. All 312 edges matched, with 0 mismatches.
- He used a solver to find the key, then proved it was unique. No second key works.

**The real result (verified):**

- The chip is a serial-key lock. It takes in a 121-bit key, one bit per clock cycle.
- If the key is right, a success signal stays on, and the output spells the flag: `(* TWO STARS *)`.
- If the key is wrong, it spells `TRY AGAIN`.
- Two jokes are hidden inside: all zeros spells `EMPTY SKY`, and all ones spells `BIG BANG`. Both keep success off.
- One wire in the layout had no driver at all. Checking it both ways gave the same key, so the answer does not depend on that wire.

**What is NOT proved / still open:**

- Nothing was submitted to Jane Street. Submissions closed on 4 September 2026, and the work was published after that close, as their post allows.
- The full 121-bit key is in the solution file. It is left out of this beginner page on purpose. You do not need to memorise 121 bits to understand the idea.
- This is a puzzle solution, not a commercial chip. It does not mean Jayant designed a chip for sale.
