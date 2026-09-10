# Reviews

KIND: REFERENCE (the verifier's report shape; the reports themselves are the semantic tier)

One file per independent review: `review-NNN-<subject>.md`, where `NNN` is the experiment or
delivery being reviewed. Both template instantiations added this directory independently: a
sign-off that exists only in a chat transcript is not evidence, and a findings list that is never
committed to a file is re-discovered by the next reader.

**Who writes one.** The `signoff-verifier` agent, or any second actor re-measuring a delivery
claim (rule 7). Never the author of the work under review. `verifiers:` in `harness.yaml` is the
closed roster of ids allowed to sign a ledger row.

**What it contains.**

1. **Scope and method** — what was re-derived (netlist, decks, GDS), what was re-run, and what was
   taken on trust. A review that only re-reads the author's numbers says so in this section.
2. **The verdict on the headline claim** — stands, narrowed, or withdrawn. State it before the table.
3. **A findings table**: `severity | finding | fix`. Severities are `blocker` (the claim does not
   survive), `major` (a number or a method is wrong), `minor` (hygiene). Every finding names its
   evidence: a ledger tag, a rawfile, or a file and line. Where the finding is a measurement, the
   row carries the reviewer's own number beside the number claimed.
4. **What was NOT checked**, explicitly. A time-boxed review with an unstated gap reads as complete.
5. **Fix round** — appended after the author responds: which findings moved, which numbers changed,
   what was re-run and what was deliberately not.

**Rules both instantiations needed.**

- *An independent re-measure is a re-run, not a re-read.* Rebuild the artefact from its committed
  generator; a scorecard the author produced is the thing being audited, not the instrument.
- *One measurement path.* If the reviewer's runner is more tolerant than the frozen one — skipping
  a bench, absorbing a warning — the two columns are not a comparison. Report the divergence as a
  finding that outranks the design verdict.
- *A finding is a hypothesis until the instrument agrees.* Change one thing, re-measure, and quote
  the delta. A textbook-correct fix can measure neutral or worse.
- *Grid artefacts.* A frontier read off a coarse sweep is a property of the sweep. Before reporting
  "X and Y are at parity", check the step between them.
- *State the gaps; do not leave the reader to find them.* Extraction blind spots, corner sets not
  re-run, rows no objective scored: list every one.
- *A red gate is not automatically a missing signature.* Demonstrate the gate can go green before
  filing it as someone else's to-do (`doc/memory/README.md` §6).

Link the review from the reviewed experiment's README and, when it changes a number, from the
journal entry that supersedes the old one.
