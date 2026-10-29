# Evaluation report: 2026-10-29T19-39-48Z_v2

- Prompt `v2` (`a63b974ab7b1`), model `nvidia/nemotron-3.5-super-vl:free` via `openrouter`; self-correction 2, value check True
- Mode: replay (source `2026-10-29T19-39-48Z_v2`)
- **Overall score: 0.79** · ran 1.00 · columns 0.58 · rows/groups 0.82 · counts 0.67
- 11 scored, 0 failed, 0 errors, skipped: none
- Tokens: 139,770 over 12 LLM calls

| # | Hypothesis | Status | Score | Ran | Columns | Rows/Groups F1 | Counts | Expected | Returned | Matched | Missing | Extra | Attempts | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Sign-in Failures (Brute Force/Bot Attacks) | scored | 0.57 | 1.00 | 0.12 | 0.57 | – | 12 | 9 | 6 | 6 | 3 | 1 | 12,579 |
| 2 | Root Access Through Console | scored | 1.00 | 1.00 | 1.00 | 0.99 | – | 61 | 62 | 61 | 0 | 1 | 1 | 11,374 |
| 3 | CloudTrail Disruption | scored | 0.84 | 1.00 | 0.37 | 1.00 | – | 4 | 4 | 4 | 0 | 0 | 1 | 11,210 |
| 4 | Unauthorized API Calls | scored | 0.93 | 1.00 | 0.75 | 0.94 | 0.99 | 2,387 | 2,679 | 2,387 | 0 | 292 | 1 | 11,379 |
| 5 | Whoami Reconnaissance | scored | 0.93 | 1.00 | 0.67 | 1.00 | 1.00 | 4,767 | 4,767 | 4,767 | 0 | 0 | 1 | 12,243 |
| 6 | Secrets Manager Access | scored | 1.00 | 1.00 | 1.00 | 1.00 | – | 1 | 1 | 1 | 0 | 0 | 1 | 11,500 |
| 7 | Large EC2 Instance Creation | scored | 0.52 | 1.00 | 0.05 | 0.77 | 0.00 | 34 | 23 | 22 | 12 | 1 | 1 | 13,262 |
| 8 | S3 Bucket Brute Force | scored | 0.87 | 1.00 | 0.83 | 0.75 | 1.00 | 212 | 350 | 212 | 0 | 138 | 1 | 11,655 |
| 9a | Suspicious User Agents | scored | 0.95 | 1.00 | 0.75 | 1.00 | 1.00 | 1,896 | 1,915 | 1,896 | 0 | 19 | 1 | 12,137 |
| 9b | Suspicious User Agents | scored | 0.33 | 1.00 | 0.67 | 0.00 | 0.00 | 101 | 535 | 0 | 101 | 535 | 2 | 21,706 |
| 10 | Permanent Key Creation | scored | 0.80 | 1.00 | 0.21 | 1.00 | – | 40 | 40 | 40 | 0 | 0 | 1 | 10,725 |

## Expected vs found

### 1. Sign-in Failures (Brute Force/Bot Attacks): scored

> **Answer-key note:** The answer key keeps only the 12 failed ConsoleLogin events. The data has 26 failed console sign-ins: 12 ConsoleLogin plus 14 CheckMfa with the same 'No username found in supplied account' message, which a hunter would also want. The hypothesis' 'brute force' wording also invites grouped counts, while the key lists events.

Expected 12 rows, returned 9 (total 9): 6 matched, 6 missing, 3 extra. Matched on `sourceIPAddress`.
API summary: 9 rows · 8 distinct userAgent

```sql
WITH failed_signins AS (SELECT userIdentityarn, sourceIPAddress, userAgent FROM cloudtrail WHERE eventSource = 'signin.amazonaws.com' AND eventType = 'AwsConsoleSignIn' AND (NOT errorCode IS NULL OR NOT errorMessage IS NULL)) SELECT userIdentityarn, sourceIPAddress, userAgent, COUNT(*) AS count FROM failed_signins GROUP BY userIdentityarn, sourceIPAddress, userAgent ORDER BY count DESC
```

Missing (expected, not returned):

- eventTime=`2017-05-17T23:23:34Z`, sourceIPAddress=`8.120.255.102`, errorMessage=`No username found in supplied account`, awsRegion=`us-east-1`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`
- eventTime=`2018-02-26T18:45:36Z`, sourceIPAddress=`12.80.110.252`, errorMessage=`No username found in supplied account`, awsRegion=`us-east-1`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`
- eventTime=`2018-02-26T18:45:51Z`, sourceIPAddress=`12.80.110.252`, errorMessage=`No username found in supplied account`, awsRegion=`us-east-1`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`

Extra (returned, not expected):

- userIdentityarn=`null`, sourceIPAddress=`25.72.52.4`, userAgent=`Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KH…`, count=`2`
- userIdentityarn=`null`, sourceIPAddress=`247.61.123.211`, userAgent=`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.3…`, count=`2`
- userIdentityarn=`null`, sourceIPAddress=`254.17.231.230`, userAgent=`Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:60.0) Gecko/9676…`, count=`2`

### 2. Root Access Through Console: scored

Expected 61 rows, returned 62 (total 62): 61 matched, 0 missing, 1 extra. Matched on `eventID`.
API summary: 62 rows · 61 distinct eventID · 14 distinct sourceIPAddress · 25 distinct userAgent · eventTime 2017-02-18 → 2020-10-07

```sql
SELECT * FROM cloudtrail WHERE eventType = 'AwsConsoleSignIn' AND userIdentitytype = 'Root' ORDER BY CAST(eventTime AS TIMESTAMP)
```

Extra (returned, not expected):

- eventID=`fc8e23e1-c025-4d45-a33a-4561b5531bc2`, eventTime=`2019-03-03T16:27:05Z`, sourceIPAddress=`2.7.223.252`, userAgent=`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit…`, eventName=`ConsoleLogin`, eventSource=`signin.amazonaws.com`, awsRegion=`us-east-1`, eventVersion=`1.05`, userIdentitytype=`Root`, eventType=`AwsConsoleSignIn`, requestID=`null`, userIdentityaccountId=`811596193553`, userIdentityprincipalId=`811596193553`, userIdentityarn=`arn:aws:iam::811596193553:root`, userIdentityaccessKeyId=`null`, userIdentityuserName=`null`, errorCode=`null`, errorMessage=`null`, requestParametersinstanceType=`null`

### 3. CloudTrail Disruption: scored

Expected 4 rows, returned 4 (total 4): 4 matched, 0 missing, 0 extra. Matched on `eventTime, errorMessage, userIdentityarn, sourceIPAddress, eventName, userAgent, awsRegion`.
API summary: 4 rows · 3 distinct eventID · 3 distinct sourceIPAddress · 3 distinct userAgent · eventTime 2017-08-03 → 2019-08-23

```sql
SELECT * FROM cloudtrail WHERE eventSource = 'cloudtrail.amazonaws.com' AND eventName IN ('StopLogging', 'DeleteTrail', 'UpdateTrail', 'PutEventSelectors') ORDER BY CAST(eventTime AS TIMESTAMP)
```

### 4. Unauthorized API Calls: scored

> **Answer-key note:** The hypothesis names AccessDenied and UnauthorizedOperation. With the real value Client.UnauthorizedOperation there are 2,679 (eventName, userIdentityarn) groups; the key has 2,387, close to AccessDenied alone (2,411), so some groups and counts cannot match.

Expected 2,387 groups, returned 2,679 (total 2,695): 2,387 matched, 0 missing, 292 extra. Matched on `eventName, userIdentityarn`.
API summary: 2,695 rows · 10 distinct userIdentityarn · 1,074 distinct eventName · 2 distinct errorCode

```sql
WITH unauthorized_calls AS (SELECT userIdentityarn, eventName, errorCode FROM cloudtrail WHERE errorCode = 'AccessDenied' OR errorCode = 'Client.UnauthorizedOperation') SELECT userIdentityarn, eventName, errorCode, COUNT(*) AS count FROM unauthorized_calls GROUP BY userIdentityarn, eventName, errorCode ORDER BY count DESC
```

Extra (returned, not expected):

- eventName=`AllocateAddress`, userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, count=`1`
- eventName=`AllocateAddress`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`3`
- eventName=`AllocateHosts`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`1`

### 5. Whoami Reconnaissance: scored

Expected 4,767 groups, returned 4,767 (total 4,767): 4,767 matched, 0 missing, 0 extra. Matched on `userIdentityarn, sourceIPAddress, userAgent`.
API summary: 4,767 rows · 6 distinct userIdentityarn · 1 distinct eventName · 3,262 distinct sourceIPAddress

```sql
SELECT userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent, COUNT(*) AS count FROM cloudtrail WHERE eventName = 'GetCallerIdentity' GROUP BY userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent ORDER BY count DESC
```

### 6. Secrets Manager Access: scored

Expected 1 rows, returned 1 (total 1): 1 matched, 0 missing, 0 extra. Matched on `eventID`.
API summary: 1 rows · eventTime 2020-02-04 → 2020-02-04

```sql
WITH secret_retrieval AS (SELECT * FROM cloudtrail WHERE eventSource = 'secretsmanager.amazonaws.com' AND eventName = 'GetSecretValue') SELECT * FROM secret_retrieval ORDER BY CAST(eventTime AS TIMESTAMP)
```

### 7. Large EC2 Instance Creation: scored

Expected 34 groups, returned 23 (total 300,622, truncated): 22 matched, 12 missing, 1 extra. Matched on `instanceType`.
API summary: 300,622 rows (first 10,000 shown; stats below cover those) · 9,680 distinct eventID · 5 distinct sourceIPAddress · 5 distinct userAgent · eventTime 2018-04-16 → 2019-08-21

```sql
SELECT * FROM cloudtrail WHERE eventName = 'RunInstances' AND (requestParametersinstanceType LIKE '%.10xlarge' OR requestParametersinstanceType LIKE '%.12xlarge' OR requestParametersinstanceType LIKE '%.16xlarge' OR requestParametersinstanceType LIKE '%.18xlarge' OR requestParametersinstanceType LIKE '%.24xlarge' OR requestParametersinstanceType LIKE '%.32xlarge' OR requestParametersinstanceType LIKE '%.metal') ORDER BY CAST(eventTime AS TIMESTAMP)
```

Missing (expected, not returned):

- instanceType=`c5.12xlarge`, count=`3758`
- instanceType=`c5.24xlarge`, count=`2923`
- instanceType=`c5d.12xlarge`, count=`3838`

Extra (returned, not expected):

- instanceType=`i3.metal`, count=`null`

### 8. S3 Bucket Brute Force: scored

> **Answer-key note:** The answer key keeps 212 of the 350 GetBucketAcl (actor, IP, user agent, error code) groups: failed requests only (AccessDenied, NoSuchBucket), and not all of those (the data has 270 failed-request groups). The hypothesis covers all attempts, so successful requests and the other failures count as extra.

Expected 212 groups, returned 350 (total 350): 212 matched, 0 missing, 138 extra. Matched on `userIdentityarn, sourceIPAddress, userAgent, errorCode`.
API summary: 350 rows · 10 distinct userIdentityarn · 1 distinct eventName · 3 distinct errorCode

```sql
WITH bucket_acl_events AS (SELECT * FROM cloudtrail WHERE eventName = 'GetBucketAcl') SELECT userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent, COUNT(*) AS count FROM bucket_acl_events GROUP BY userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent ORDER BY count DESC
```

Extra (returned, not expected):

- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`2.251.230.253`, userAgent=`[S3Console/0.4, aws-internal/3 aws-sdk-java/1.11.408 Linux/…`, errorCode=`null`, count=`2`
- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`2.251.230.253`, userAgent=`[S3Console/0.4]`, errorCode=`null`, count=`10`
- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`250.251.253.3`, userAgent=`[S3Console/0.4, aws-internal/3 aws-sdk-java/1.11.347 Linux/…`, errorCode=`null`, count=`13`

### 9a. Suspicious User Agents: scored

Expected 1,896 groups, returned 1,915 (total 2,344): 1,896 matched, 0 missing, 19 extra. Matched on `userIdentityarn, userAgent`.
API summary: 2,344 rows · 4 distinct userIdentityarn · 895 distinct sourceIPAddress · 1,477 distinct userAgent

```sql
SELECT userIdentityarn, sourceIPAddress, userAgent, COUNT(*) AS count FROM cloudtrail WHERE userAgent ILIKE '%kali%' OR userAgent ILIKE '%parrot%' OR userAgent ILIKE '%powershell%' GROUP BY userIdentityarn, sourceIPAddress, userAgent ORDER BY count DESC
```

Extra (returned, not expected):

- userIdentityarn=`null`, userAgent=`[Boto3/1.13.1 Python/2.7.18 Linux/5.4.0-kali3-amd64 Botocor…`, count=`3`
- userIdentityarn=`null`, userAgent=`[Boto3/1.13.12 Python/3.8.5 Linux/5.7.0-kali1-amd64 Botocor…`, count=`1`
- userIdentityarn=`null`, userAgent=`[Boto3/1.13.12 Python/3.8.6 Linux/5.4.0-kali3-amd64 Botocor…`, count=`2`

### 9b. Suspicious User Agents: scored

> **Answer-key note:** The answer key's userAgent values are the 'command/...' substring extracted from longer user-agent strings. No userAgent in the data starts with 'command/', so no query over the raw column can reproduce these groups.

Expected 101 groups, returned 535 (total 587): 0 matched, 101 missing, 535 extra. Matched on `userAgent`.
API summary: 587 rows · 4 distinct userIdentityarn · 535 distinct userAgent

```sql
WITH suspicious AS (SELECT userIdentityarn, userAgent FROM cloudtrail WHERE userAgent LIKE '%command/%') SELECT userIdentityarn, userAgent, COUNT(*) AS count FROM suspicious GROUP BY userIdentityarn, userAgent ORDER BY count DESC
```

Missing (expected, not returned):

- userAgent=`command/acm.list-certificates`, count=`1`
- userAgent=`command/apigateway.create-authorizer`, count=`1`
- userAgent=`command/apigateway.get-account`, count=`5`

Extra (returned, not expected):

- userAgent=`[aws-cli/2.0.36 Python/3.7.3 Linux/5.0.0-38-generic exe/x86…`, count=`4`
- userAgent=`[aws-cli/2.0.36 Python/3.7.3 Linux/5.0.0-38-generic exe/x86…`, count=`1`
- userAgent=`[aws-cli/2.0.36 Python/3.7.3 Linux/5.0.0-38-generic exe/x86…`, count=`1`

### 10. Permanent Key Creation: scored

Expected 40 rows, returned 40 (total 40): 40 matched, 0 missing, 0 extra. Matched on `sourceIPAddress, userIdentityarn, errorCode, errorMessage`.
API summary: 40 rows · 32 distinct eventID · 20 distinct sourceIPAddress · 20 distinct userAgent · eventTime 2017-03-01 → 2020-05-14

```sql
WITH iam_user_key_creation AS (SELECT * FROM cloudtrail WHERE eventName = 'CreateAccessKey' AND userIdentitytype = 'IAMUser') SELECT * FROM iam_user_key_creation ORDER BY CAST(eventTime AS TIMESTAMP)
```

