# Evaluation Report

How well the query generator answers the 11 known hypotheses, measured strictly against `hypotheses_outcomes.json`,
before and after one round of prompt and harness improvements.

**Summary:** the overall score rose from **0.50 to 0.79**. Every query ran in both runs. The gain comes from answering
in the right shape (grouped counts went from 0.00 to 0.67 correct), finding the right events or groups (0.49 → 0.82),
and returning the expected columns (0.26 → 0.58). Of the gap that remains, the largest part is the answer key scoping
some hypotheses more narrowly than their wording, explained per hypothesis below. One real query weakness remains (#7).

> The same results as a page: open [`evaluation_dashboard.html`](evaluation_dashboard.html) in a browser.

## 1. The two runs
| | Before | After |
|---|---|---|
| Run folder | [`runs/2026-10-29T19-19-34Z_v1`](runs/2026-10-29T19-19-34Z_v1/report.md) | [`runs/2026-10-29T19-39-48Z_v2`](runs/2026-10-29T19-39-48Z_v2/report.md) |
| Prompt | v1 (`9cd12dc42e98`): role, SQL rules, output contract, schema card | v2 (`a63b974ab7b1`): v1 + seven generic rules from the failure analysis |
| Self-correction | off | up to 2 corrections |
| Zero-row value check | off | on |
| Model | `nvidia/nemotron-3.5-super-vl:free` via OpenRouter | same |
| User / budget | fresh user, 200,000 tokens per 6h window | same |
| Tokens used | 121,673 over 11 LLM calls | 139,770 over 12 LLM calls (60,230 left) |
| Failed / skipped | 0 / 0 | 0 / 0 |

Both runs went through `main.py` against the running API over real HTTP, one hypothesis at a time, exactly as a client
would. `run_config.json` in each folder records the server's settings as reported by `/healthz`. `--replay` re-scores
either run from its saved responses and reproduces these numbers.

## 2. How a score is made
Each hypothesis gets a score from 0 to 1, the weighted sum of four checks (APPROACH §9.5):

| Check | Question | Weight |
|---|---|---|
| Ran | Did the SQL run? | 20% |
| Right columns | Overlap (Jaccard) between expected and returned columns | 20% |
| Right rows / groups | F1 of the events (matched on `eventID` or the shared columns) or of the groups (matched on the group keys) | 40% |
| Right counts | For grouped answers, share of matched groups with exactly the expected count | 20% |

Answers that list events have no counts, so their weights become 25 / 25 / 50. A failed query scores 0. Values are
normalised first (numbers, nulls, timestamps, column aliases such as `instanceType` ↔ `requestParametersinstanceType`).
The overall score is the plain average over hypotheses.

The scorer was checked before use: the answer key scored against itself gives 1.0 on all 11, and hand-written correct
SQL on the real data gives 0.996 for #2 (61 of 61 rows plus one extra event) and 1.0 for #7.

## 3. Results
| Check | Before | After | Δ |
|---|---|---|---|
| **Overall** | **0.50** | **0.79** | **+0.29** |
| Ran | 1.00 | 1.00 | ±0.00 |
| Right columns | 0.26 | 0.58 | +0.32 |
| Right rows / groups | 0.49 | 0.82 | +0.33 |
| Right counts | 0.00 | 0.67 | +0.67 |

| # | Hypothesis | Answer key | Before | After | Δ |
|---|---|---|---|---|---|
| 1 | Sign-in Failures (Brute Force/Bot Attacks) | 12 events | 0.27 | 0.57 | +0.30 |
| 2 | Root Access Through Console | 61 events | 0.89 | **1.00** | +0.11 |
| 3 | CloudTrail Disruption | 4 events | 0.54 | 0.84 | +0.30 |
| 4 | Unauthorized API Calls | 2,387 groups | 0.51 | 0.93 | +0.41 |
| 5 | Whoami Reconnaissance | 4,767 groups | 0.53 | 0.93 | +0.40 |
| 6 | Secrets Manager Access | 1 event | 0.40 | **1.00** | +0.60 |
| 7 | Large EC2 Instance Creation | 34 groups | 0.57 | 0.52 | −0.05 |
| 8 | S3 Bucket Brute Force | 212 groups | 0.38 | 0.87 | +0.49 |
| 9a | Suspicious User Agents (kali, parrot, powershell) | 1,896 groups | 0.40 | 0.95 | +0.55 |
| 9b | Suspicious User Agents (`command/*`) | 101 groups | 0.22 | 0.33 | +0.12 |
| 10 | Permanent Key Creation | 40 events | 0.81 | 0.80 | ±0.00 |

## 4. What changed, and why it helped
The v1 failures fell into a few patterns. Each became a rule in v2 that holds for any hypothesis; none names a
hypothesis or an answer-key value (full table with reasons in APPROACH §15).

1. **Wrong output shape:** "who / how often / with what" hypotheses (4, 5, 7, 8, 9a, 9b) came back as raw events, so
   they had no counts and were cut at the 10,000-row cap. v2 picks grouped counts for those, with
   `COUNT(*) AS count` and no extra metrics. Counts went from 0.00 to 0.67; #4, #5, #8 and #9a now match every expected
   group, mostly with exact counts.
2. **Too broad a filter:** #3 included trail creation and #6 included listing and describing secrets. v2 matches only
   the actions that perform the behaviour. #6 went from 398 events to exactly the 1 expected; #3 from 25 to the 4
   expected.
3. **Partial columns for events:** event answers returned arbitrary column subsets. v2 returns complete events; #2 and
   #6 now match all 19 columns.
4. **Invented cut-offs:** `HAVING COUNT(*) >= 5` and `LIMIT 100` silently dropped findings in #1 and #8. v2 adds none.
5. **A data trap:** failed console sign-ins have no `errorCode`, only `errorMessage`, so v1's #1 returned 0 rows. v2
   states this; #1 now finds the failures.

Self-correction was used once in the after run: #9b's first query returned 0 rows, the value check reported that its
`LIKE 'command/%'` pattern matched no user agent, and the second attempt widened it to `'%command/%'`.

## 5. Expected vs found, per hypothesis (after run)
**1. Sign-in failures: 0.57.** Found 9 (actor, IP, user agent) groups of failed console sign-ins. The answer is grouped
where the key lists events, so the two share one column (source IP), and 6 of the 12 expected events match on it. *Answer-key note:* the key keeps only
the 12 failed `ConsoleLogin` events; the data has 26 failed console sign-ins (12 `ConsoleLogin` + 14 `CheckMfa` with the
same "No username found in supplied account" message), which a hunter would also want. The hypothesis says "brute force",
which reasonably invites counts.

**2. Root console access: 1.00.** All 61 expected root `AwsConsoleSignIn` events with all 19 columns, plus one more
root console sign-in event that the key doesn't list.

**3. CloudTrail disruption: 0.84.** Exactly the 4 expected events (`StopLogging` ×2, `UpdateTrail`, `DeleteTrail`).
The score loss is columns only: complete events (19 columns) vs the key's 7.

**4. Unauthorized API calls: 0.93.** All 2,387 expected (action, actor) groups found, with 99% of counts exact; 292
extra groups. *Answer-key note:* the hypothesis names AccessDenied and UnauthorizedOperation, and the real value is
`Client.UnauthorizedOperation`; with both there are 2,679 groups, while the key has 2,387 (close to AccessDenied alone).

**5. Whoami reconnaissance: 0.93.** All 4,767 expected (actor, IP, user agent) groups, every count exact. The query
also grouped by `eventName` and `errorCode`, which costs columns only.

**6. Secrets Manager access: 1.00.** The single `GetSecretValue` event, complete.

**7. Large EC2 instances: 0.52.** The filter is right (`RunInstances` with 10xlarge or bigger), but the model returned
raw events rather than counts per instance type. 300,622 events matched, the first 10,000 were returned, so only 22 of 34
types appear and no counts can be compared. This is the one remaining real query weakness; a generic harness fix is
proposed in §7.

**8. S3 bucket brute force: 0.87.** All 212 expected (actor, IP, user agent, error code) groups with exact counts,
plus 138 extra groups: 80 of successful requests and 58 failed ones the key leaves out. *Answer-key note:* the key
keeps 212 of the 270 failed-request groups (AccessDenied, NoSuchBucket) and no successful ones; the hypothesis covers
all attempts.

**9a. Suspicious user agents (kali, parrot, powershell): 0.95.** All 1,896 expected (actor, user agent) groups with
exact counts. The query also grouped by source IP, which leaves 19 extra groups after regrouping.

**9b. Suspicious user agents (`command/*`): 0.33.** 535 groups found, none matching. *Answer-key note:* the key's user
agents are the `command/…` substring extracted from longer strings (e.g. `command/ec2.describe-snapshots`); no user agent
in the data starts with `command/`, so no query over the raw column can reproduce these groups.

**10. Permanent key creation: 0.80.** Exactly the 40 expected `CreateAccessKey` events by IAM users. The score loss is
columns only (19 vs the key's 4).

## 6. Limitations of this evaluation
- **One run per configuration, on a free model.** LLM output varies between runs, so differences of a few hundredths
  on one hypothesis are noise. The overall trend (+0.29, with every check improving) is far larger than that.
- **Prompt, self-correction and value check changed together**, so the gain can't be split between them. In the after
  run only one hypothesis (#9b) needed a correction, so most of the gain is the prompt.
- **Strict scoring** penalises answers that are right but scoped or grouped differently from the key (#1, #4, #8, #9b
  above, and the column counts of #3, #10). The notes explain these cases; the score doesn't credit them.
- **The prompt was improved using failures on these same 11 hypotheses.** The rules are generic by design and checked
  for hypothesis-specific terms, but there is no held-out set to prove they generalise.
- **The production model was not used.** The official runs used a free OpenRouter model (D44); the default
  configuration targets Claude Sonnet 5.5, which would likely score higher and differently.

## 7. Next improvements
- **Truncation feedback** (fixes #7): when an events answer exceeds the row cap, send that back as a correction
  ("summarise with grouped counts") instead of returning a truncated list.
- **Relaxed score** next to the strict one: ignore extra columns and roll finer groupings up to the key's grouping,
  so the report separates "wrong" from "differently scoped".
- **Ablation runs** (self-correction only, + value check, + prompt v2) to attribute the gain.
- **Repeated runs** per configuration to report variance.
