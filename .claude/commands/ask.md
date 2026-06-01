# /ask — Token-saving memory command

Answer **$ARGUMENTS** using a persistent JSON memory cache to eliminate repeated token spend.

## Step 1 — Check cache

Read `~/.cache/token-saver/memory.json` (create empty `{}` if it does not exist).

Compute the SHA-256 of the lowercased, trimmed question (first 16 hex chars = the key).

Also check for **fuzzy matches**: for each cached entry, compute keyword overlap between
the incoming question and the stored question (strip stop words, compare sets).
If overlap ≥ 80%, treat it as a fuzzy hit.

## Step 2 — Return cached answer if available

If an exact or fuzzy match exists:
- Reply with the cached answer.
- Prefix fuzzy hits with `[~cached from similar question]`.
- Add one line: `✓ cached — 0 tokens spent`.
- Increment `hit_count` on the matching entry and write the file back.
- **Stop here.** Do not call the API.

## Step 3 — Answer fresh (no cache hit)

Answer **$ARGUMENTS** using these strict rules:
- **No preamble** ("Sure!", "Great question!", "Of course!" — forbidden).
- **No postamble** ("Let me know if...", "Hope that helps!" — forbidden).
- Prefer code over prose for technical questions.
- Bullet points, not paragraphs.
- Do not restate the question.

## Step 4 — Save to cache

After answering fresh, append to `~/.cache/token-saver/memory.json`:

```json
"<16-char-sha256-key>": {
  "question": "<exact question text>",
  "answer": "<your answer>",
  "model": "claude (code)",
  "tokens_used": 0,
  "created_at": "<ISO-8601 UTC timestamp>",
  "hit_count": 0
}
```

Also print: `↓ fresh — answer cached for next time`.

## Stop words (exclude from keyword matching)
a, an, the, is, it, in, on, at, to, for, of, and, or, but, how, what, why,
when, where, which, who, does, do, i, my, me, you, your, be, are, was, were,
this, that, with, from, by, as, if
