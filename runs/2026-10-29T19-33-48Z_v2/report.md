# Evaluation report: 2026-10-29T19-33-48Z_v2

- Prompt `v2` (`1761c0325962`), model `nvidia/nemotron-3.5-super-vl:free` via `openrouter`; self-correction 2, value check True
- Mode: replay (source `2026-10-29T19-33-48Z_v2`)
- **Overall score: 0.71** · ran 1.00 · columns 0.49 · rows/groups 0.75 · counts 0.36
- 11 scored, 0 failed, 0 errors, skipped: none
- Tokens: 135,114 over 12 LLM calls

| # | Hypothesis | Status | Score | Ran | Columns | Rows/Groups F1 | Counts | Expected | Returned | Matched | Missing | Extra | Attempts | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Sign-in Failures (Brute Force/Bot Attacks) | scored | 0.63 | 1.00 | 0.26 | 0.63 | – | 12 | 26 | 12 | 0 | 14 | 1 | 10,940 |
| 2 | Root Access Through Console | scored | 1.00 | 1.00 | 1.00 | 0.99 | – | 61 | 62 | 61 | 0 | 1 | 1 | 11,184 |
| 3 | CloudTrail Disruption | scored | 0.84 | 1.00 | 0.37 | 1.00 | – | 4 | 4 | 4 | 0 | 0 | 1 | 10,619 |
| 4 | Unauthorized API Calls | scored | 0.65 | 1.00 | 0.50 | 0.80 | 0.17 | 2,387 | 1,818 | 1,676 | 711 | 142 | 1 | 11,097 |
| 5 | Whoami Reconnaissance | scored | 0.96 | 1.00 | 0.80 | 1.00 | 1.00 | 4,767 | 4,767 | 4,767 | 0 | 0 | 1 | 11,017 |
| 6 | Secrets Manager Access | scored | 1.00 | 1.00 | 1.00 | 1.00 | – | 1 | 1 | 1 | 0 | 0 | 1 | 11,758 |
| 7 | Large EC2 Instance Creation | scored | 0.52 | 1.00 | 0.05 | 0.77 | 0.00 | 34 | 23 | 22 | 12 | 1 | 1 | 12,507 |
| 8 | S3 Bucket Brute Force | scored | 0.90 | 1.00 | 1.00 | 0.75 | 1.00 | 212 | 350 | 212 | 0 | 138 | 1 | 11,526 |
| 9a | Suspicious User Agents | scored | 0.35 | 1.00 | 0.10 | 0.31 | 0.00 | 1,896 | 354 | 354 | 1,542 | 0 | 1 | 11,211 |
| 9b | Suspicious User Agents | scored | 0.21 | 1.00 | 0.05 | 0.00 | 0.00 | 101 | 535 | 0 | 101 | 535 | 2 | 22,163 |
| 10 | Permanent Key Creation | scored | 0.80 | 1.00 | 0.21 | 1.00 | – | 40 | 40 | 40 | 0 | 0 | 1 | 11,092 |

## Expected vs found

### 1. Sign-in Failures (Brute Force/Bot Attacks): scored

> **Answer-key note:** The answer key keeps only the 12 failed ConsoleLogin events. The data has 26 failed console sign-ins: 12 ConsoleLogin plus 14 CheckMfa with the same 'No username found in supplied account' message, which a hunter would also want. The hypothesis' 'brute force' wording also invites grouped counts, while the key lists events.

Expected 12 rows, returned 26 (total 26): 12 matched, 0 missing, 14 extra. Matched on `eventTime, sourceIPAddress, errorMessage, awsRegion, userIdentityuserName`.
API summary: 26 rows · 9 distinct sourceIPAddress · 8 distinct userAgent · 2 distinct eventName · eventTime 2017-05-17 → 2020-01-18

```sql
SELECT * FROM cloudtrail WHERE eventType = 'AwsConsoleSignIn' AND (NOT errorCode IS NULL OR NOT errorMessage IS NULL) ORDER BY CAST(eventTime AS TIMESTAMP)
```

Extra (returned, not expected):

- eventID=`5bae1ed3-fd9c-47df-a6d4-3d76fc3f3480`, eventTime=`2017-05-17T23:23:34Z`, sourceIPAddress=`8.120.255.102`, userAgent=`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) AppleWebKit…`, eventName=`CheckMfa`, eventSource=`signin.amazonaws.com`, awsRegion=`us-east-1`, eventVersion=`1.05`, userIdentitytype=`IAMUser`, eventType=`AwsConsoleSignIn`, requestID=`null`, userIdentityaccountId=`811596193553`, userIdentityprincipalId=`null`, userIdentityarn=`null`, userIdentityaccessKeyId=`null`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`, errorCode=`null`, errorMessage=`No username found in supplied account`, requestParametersinstanceType=`null`
- eventID=`4837b058-7c74-49de-86a1-eab37d83c000`, eventTime=`2017-05-17T23:23:40Z`, sourceIPAddress=`8.120.255.102`, userAgent=`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) AppleWebKit…`, eventName=`CheckMfa`, eventSource=`signin.amazonaws.com`, awsRegion=`us-east-1`, eventVersion=`1.05`, userIdentitytype=`IAMUser`, eventType=`AwsConsoleSignIn`, requestID=`null`, userIdentityaccountId=`811596193553`, userIdentityprincipalId=`null`, userIdentityarn=`null`, userIdentityaccessKeyId=`null`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`, errorCode=`null`, errorMessage=`No username found in supplied account`, requestParametersinstanceType=`null`
- eventID=`94c89a1b-aa0c-4da5-ac56-dc173306fa7e0`, eventTime=`2018-02-26T01:12:46Z`, sourceIPAddress=`231.17.3.165`, userAgent=`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_3) AppleWebKit…`, eventName=`CheckMfa`, eventSource=`signin.amazonaws.com`, awsRegion=`us-east-1`, eventVersion=`1.05`, userIdentitytype=`IAMUser`, eventType=`AwsConsoleSignIn`, requestID=`null`, userIdentityaccountId=`811596193553`, userIdentityprincipalId=`null`, userIdentityarn=`null`, userIdentityaccessKeyId=`null`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`, errorCode=`null`, errorMessage=`No username found in supplied account`, requestParametersinstanceType=`null`

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
WITH disruptive_events AS (SELECT * FROM cloudtrail WHERE eventSource = 'cloudtrail.amazonaws.com' AND eventName IN ('StopLogging', 'DeleteTrail', 'UpdateTrail')) SELECT * FROM disruptive_events ORDER BY CAST(eventTime AS TIMESTAMP)
```

### 4. Unauthorized API Calls: scored

> **Answer-key note:** The hypothesis names AccessDenied and UnauthorizedOperation. With the real value Client.UnauthorizedOperation there are 2,679 (eventName, userIdentityarn) groups; the key has 2,387, close to AccessDenied alone (2,411), so some groups and counts cannot match.

Expected 2,387 groups, returned 1,818 (total 23,010, truncated): 1,676 matched, 711 missing, 142 extra. Matched on `eventName, userIdentityarn`.
API summary: 23,010 rows (first 10,000 shown; stats below cover those) · 9 distinct userIdentityarn · 791 distinct eventName · 2 distinct errorCode

```sql
WITH unauthorized AS (SELECT userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent FROM cloudtrail WHERE errorCode IN ('AccessDenied', 'Client.UnauthorizedOperation')) SELECT userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent, COUNT(*) AS count FROM unauthorized GROUP BY userIdentityarn, eventName, errorCode, sourceIPAddress, userAgent ORDER BY count DESC
```

Missing (expected, not returned):

- eventName=`AddRoleToInstanceProfile`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`1`
- eventName=`AttachGroupPolicy`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`2`
- eventName=`AttachRolePolicy`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`2`

Extra (returned, not expected):

- eventName=`AllocateAddress`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`3`
- eventName=`AttachVolume`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`5`
- eventName=`AuthorizeSecurityGroupIngress`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`2`

### 5. Whoami Reconnaissance: scored

Expected 4,767 groups, returned 4,767 (total 4,767): 4,767 matched, 0 missing, 0 extra. Matched on `userIdentityarn, sourceIPAddress, userAgent`.
API summary: 4,767 rows · 6 distinct userIdentityarn · 1 distinct eventName · 3,262 distinct sourceIPAddress

```sql
WITH filtered AS (SELECT userIdentityarn, eventName, sourceIPAddress, userAgent FROM cloudtrail WHERE eventName = 'GetCallerIdentity') SELECT userIdentityarn, eventName, sourceIPAddress, userAgent, COUNT(*) AS count FROM filtered GROUP BY userIdentityarn, eventName, sourceIPAddress, userAgent ORDER BY count DESC
```

### 6. Secrets Manager Access: scored

Expected 1 rows, returned 1 (total 1): 1 matched, 0 missing, 0 extra. Matched on `eventID`.
API summary: 1 rows · eventTime 2020-02-04 → 2020-02-04

```sql
SELECT * FROM cloudtrail WHERE eventSource = 'secretsmanager.amazonaws.com' AND eventName = 'GetSecretValue' ORDER BY CAST(eventTime AS TIMESTAMP)
```

### 7. Large EC2 Instance Creation: scored

Expected 34 groups, returned 23 (total 300,622, truncated): 22 matched, 12 missing, 1 extra. Matched on `instanceType`.
API summary: 300,622 rows (first 10,000 shown; stats below cover those) · 9,680 distinct eventID · 5 distinct sourceIPAddress · 5 distinct userAgent · eventTime 2018-04-16 → 2019-08-21

```sql
WITH large_instance_launches AS (SELECT * FROM cloudtrail WHERE eventName = 'RunInstances' AND (requestParametersinstanceType LIKE '%10xlarge%' OR requestParametersinstanceType LIKE '%12xlarge%' OR requestParametersinstanceType LIKE '%16xlarge%' OR requestParametersinstanceType LIKE '%18xlarge%' OR requestParametersinstanceType LIKE '%24xlarge%' OR requestParametersinstanceType LIKE '%32xlarge%' OR requestParametersinstanceType LIKE '%metal%')) SELECT * FROM large_instance_launches ORDER BY eventTime
```

Missing (expected, not returned):

- instanceType=`c5.12xlarge`, count=`3758`
- instanceType=`c5.24xlarge`, count=`2923`
- instanceType=`c5d.12xlarge`, count=`3838`

Extra (returned, not expected):

- instanceType=`i3.metal`, count=`null`

### 8. S3 Bucket Brute Force: scored

> **Answer-key note:** The answer key keeps only failed GetBucketAcl requests (AccessDenied, NoSuchBucket): 212 of the 350 (actor, IP, user agent, error code) groups. The hypothesis covers all attempts, so successful ones count as extra.

Expected 212 groups, returned 350 (total 350): 212 matched, 0 missing, 138 extra. Matched on `userIdentityarn, sourceIPAddress, userAgent, errorCode`.
API summary: 350 rows · 10 distinct userIdentityarn · 249 distinct sourceIPAddress · 287 distinct userAgent

```sql
WITH s3_acl_requests AS (SELECT userIdentityarn, sourceIPAddress, userAgent, errorCode FROM cloudtrail WHERE eventName = 'GetBucketAcl') SELECT userIdentityarn, sourceIPAddress, userAgent, errorCode, COUNT(*) AS count FROM s3_acl_requests GROUP BY userIdentityarn, sourceIPAddress, userAgent, errorCode ORDER BY count DESC
```

Extra (returned, not expected):

- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`2.251.230.253`, userAgent=`[S3Console/0.4, aws-internal/3 aws-sdk-java/1.11.408 Linux/…`, errorCode=`null`, count=`2`
- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`2.251.230.253`, userAgent=`[S3Console/0.4]`, errorCode=`null`, count=`10`
- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`250.251.253.3`, userAgent=`[S3Console/0.4, aws-internal/3 aws-sdk-java/1.11.347 Linux/…`, errorCode=`null`, count=`13`

### 9a. Suspicious User Agents: scored

Expected 1,896 groups, returned 354 (total 156,930, truncated): 354 matched, 1,542 missing, 0 extra. Matched on `userIdentityarn, userAgent`.
API summary: 156,930 rows (first 10,000 shown; stats below cover those) · 9,998 distinct eventID · 206 distinct sourceIPAddress · 282 distinct userAgent · eventTime 2017-02-27 → 2018-07-31

```sql
SELECT * FROM cloudtrail WHERE userAgent ILIKE '%kali%' OR userAgent ILIKE '%parrot%' OR userAgent ILIKE '%powershell%' ORDER BY CAST(eventTime AS TIMESTAMP)
```

Missing (expected, not returned):

- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, userAgent=`AWSPowerShell/226.1.255.1 .NET_Runtime/4.0 .NET_Framework/4…`, count=`74`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, userAgent=`AWSPowerShell/252.6.234.251 .NET_Runtime/3.-1 .NET_Framewor…`, count=`37`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, userAgent=`AWSPowerShell/3.3.542.0 .NET_Runtime/4.0 .NET_Framework/4.0…`, count=`24`

### 9b. Suspicious User Agents: scored

> **Answer-key note:** The answer key's userAgent values are the 'command/...' substring extracted from longer user-agent strings. No userAgent in the data starts with 'command/', so no query over the raw column can reproduce these groups.

Expected 101 groups, returned 535 (total 3,047): 0 matched, 101 missing, 535 extra. Matched on `userAgent`.
API summary: 3,047 rows · 97 distinct sourceIPAddress · 535 distinct userAgent · 99 distinct eventName · eventTime 2020-08-03 → 2020-10-07

```sql
SELECT * FROM cloudtrail WHERE userAgent LIKE '%command/%' ORDER BY CAST(eventTime AS TIMESTAMP)
```

Missing (expected, not returned):

- userAgent=`command/acm.list-certificates`, count=`1`
- userAgent=`command/apigateway.create-authorizer`, count=`1`
- userAgent=`command/apigateway.get-account`, count=`5`

Extra (returned, not expected):

- userAgent=`[aws-cli/2.0.36 Python/3.7.3 Linux/5.0.0-38-generic exe/x86…`, count=`null`
- userAgent=`[aws-cli/2.0.36 Python/3.7.3 Linux/5.0.0-38-generic exe/x86…`, count=`null`
- userAgent=`[aws-cli/2.0.36 Python/3.7.3 Linux/5.0.0-38-generic exe/x86…`, count=`null`

### 10. Permanent Key Creation: scored

Expected 40 rows, returned 40 (total 40): 40 matched, 0 missing, 0 extra. Matched on `sourceIPAddress, userIdentityarn, errorCode, errorMessage`.
API summary: 40 rows · 32 distinct eventID · 20 distinct sourceIPAddress · 20 distinct userAgent · eventTime 2017-03-01 → 2020-05-14

```sql
WITH iam_key_creation AS (SELECT * FROM cloudtrail WHERE eventName = 'CreateAccessKey' AND userIdentitytype = 'IAMUser') SELECT * FROM iam_key_creation ORDER BY CAST(eventTime AS TIMESTAMP)
```

