# Evaluation report: 2026-10-29T19-19-34Z_v1

- Prompt `v1` (`9cd12dc42e98`), model `nvidia/nemotron-3.5-super-vl:free` via `openrouter`; self-correction 0, value check False
- Mode: replay (source `2026-10-29T19-19-34Z_v1`)
- **Overall score: 0.50** · ran 1.00 · columns 0.26 · rows/groups 0.49 · counts 0.00
- 11 scored, 0 failed, 0 errors, skipped: none
- Tokens: 121,673 over 11 LLM calls

| # | Hypothesis | Status | Score | Ran | Columns | Rows/Groups F1 | Counts | Expected | Returned | Matched | Missing | Extra | Attempts | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Sign-in Failures (Brute Force/Bot Attacks) | scored | 0.27 | 1.00 | 0.08 | 0.00 | – | 12 | 0 | 0 | 12 | 0 | 1 | 12,169 |
| 2 | Root Access Through Console | scored | 0.89 | 1.00 | 0.58 | 0.99 | – | 61 | 62 | 61 | 0 | 1 | 1 | 10,587 |
| 3 | CloudTrail Disruption | scored | 0.54 | 1.00 | 0.60 | 0.28 | – | 4 | 25 | 4 | 0 | 21 | 1 | 10,504 |
| 4 | Unauthorized API Calls | scored | 0.51 | 1.00 | 0.15 | 0.71 | 0.00 | 2,387 | 1,500 | 1,372 | 1,015 | 128 | 1 | 10,583 |
| 5 | Whoami Reconnaissance | scored | 0.53 | 1.00 | 0.20 | 0.73 | 0.00 | 4,767 | 2,720 | 2,720 | 2,047 | 0 | 1 | 10,602 |
| 6 | Secrets Manager Access | scored | 0.40 | 1.00 | 0.58 | 0.01 | – | 1 | 398 | 1 | 0 | 397 | 1 | 11,345 |
| 7 | Large EC2 Instance Creation | scored | 0.57 | 1.00 | 0.08 | 0.89 | 0.00 | 34 | 42 | 34 | 0 | 8 | 1 | 12,029 |
| 8 | S3 Bucket Brute Force | scored | 0.38 | 1.00 | 0.15 | 0.37 | 0.00 | 163 | 67 | 42 | 121 | 25 | 1 | 11,422 |
| 9a | Suspicious User Agents | scored | 0.40 | 1.00 | 0.18 | 0.41 | 0.00 | 1,896 | 485 | 485 | 1,411 | 0 | 1 | 10,649 |
| 9b | Suspicious User Agents | scored | 0.22 | 1.00 | 0.08 | 0.00 | 0.00 | 101 | 535 | 0 | 101 | 535 | 1 | 10,615 |
| 10 | Permanent Key Creation | scored | 0.81 | 1.00 | 0.22 | 1.00 | – | 40 | 40 | 40 | 0 | 0 | 1 | 11,168 |

## Expected vs found

### 1. Sign-in Failures (Brute Force/Bot Attacks): scored

> **Answer-key note:** The answer key keeps only the 12 failed ConsoleLogin events. The data has 26 failed console sign-ins: 12 ConsoleLogin plus 14 CheckMfa with the same 'No username found in supplied account' message, which a hunter would also want. The hypothesis' 'brute force' wording also invites grouped counts, while the key lists events.

Expected 12 rows, returned 0 (total 0): 0 matched, 12 missing, 0 extra. Matched on `sourceIPAddress`.
API summary: 0 rows

```sql
WITH failed_console_logins AS (SELECT eventTime, sourceIPAddress, userAgent, userIdentitytype, userIdentityarn, userIdentityaccountId, errorCode, errorMessage, awsRegion FROM cloudtrail WHERE eventSource = 'signin.amazonaws.com' AND NOT errorCode IS NULL) SELECT sourceIPAddress, userAgent, COUNT(*) AS failed_login_count, MIN(CAST(eventTime AS TIMESTAMP)) AS first_attempt_time, MAX(CAST(eventTime AS TIMESTAMP)) AS last_attempt_time, COUNT(DISTINCT userIdentityarn) AS distinct_user_arns, COUNT(DISTINCT userIdentityaccountId) AS distinct_account_ids, LISTAGG(DISTINCT errorCode, ', ') AS observed_error_codes FROM failed_console_logins GROUP BY sourceIPAddress, userAgent HAVING COUNT(*) >= 5 ORDER BY failed_login_count DESC, sourceIPAddress
```

Missing (expected, not returned):

- eventTime=`2017-05-17T23:23:34Z`, sourceIPAddress=`8.120.255.102`, errorMessage=`No username found in supplied account`, awsRegion=`us-east-1`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`
- eventTime=`2017-05-17T23:23:41Z`, sourceIPAddress=`8.120.255.102`, errorMessage=`No username found in supplied account`, awsRegion=`us-east-1`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`
- eventTime=`2018-02-26T01:12:46Z`, sourceIPAddress=`231.17.3.165`, errorMessage=`No username found in supplied account`, awsRegion=`us-east-1`, userIdentityuserName=`HIDDEN_DUE_TO_SECURITY_REASONS`

### 2. Root Access Through Console: scored

Expected 61 rows, returned 62 (total 62): 61 matched, 0 missing, 1 extra. Matched on `eventTime, sourceIPAddress, userAgent, eventName, eventSource, awsRegion, userIdentitytype, userIdentityaccountId, userIdentityarn, errorCode, errorMessage`.
API summary: 62 rows · 1 distinct eventName · 1 distinct eventSource · 1 distinct userIdentitytype · eventTime 2017-02-18 → 2020-10-07

```sql
WITH root_console AS (SELECT eventTime, eventName, eventSource, userIdentitytype, userIdentityarn, userIdentityaccountId, sourceIPAddress, userAgent, awsRegion, errorCode, errorMessage FROM cloudtrail WHERE (userIdentitytype = 'Root' OR userIdentityarn LIKE '%:root') AND (eventType = 'AwsConsoleSignIn' OR eventSource = 'signin.amazonaws.com' OR eventName ILIKE '%ConsoleLogin%')) SELECT * FROM root_console ORDER BY CAST(eventTime AS TIMESTAMP) DESC
```

Extra (returned, not expected):

- eventTime=`2019-03-03T16:27:05Z`, eventName=`ConsoleLogin`, eventSource=`signin.amazonaws.com`, userIdentitytype=`Root`, userIdentityarn=`arn:aws:iam::811596193553:root`, userIdentityaccountId=`811596193553`, sourceIPAddress=`2.7.223.252`, userAgent=`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit…`, awsRegion=`us-east-1`, errorCode=`null`, errorMessage=`null`

### 3. CloudTrail Disruption: scored

Expected 4 rows, returned 25 (total 25): 4 matched, 0 missing, 21 extra. Matched on `eventTime, errorMessage, userIdentityarn, sourceIPAddress, eventName, awsRegion`.
API summary: 25 rows · 3 distinct userIdentityarn · 1 distinct eventSource · 4 distinct eventName · eventTime 2017-02-12 → 2019-08-23

```sql
WITH cloudtrail_events AS (SELECT eventID, eventTime, userIdentityarn, eventSource, eventName, awsRegion, sourceIPAddress, errorCode, errorMessage FROM cloudtrail WHERE eventSource = 'cloudtrail.amazonaws.com' AND eventName IN ('StopLogging', 'DeleteTrail', 'UpdateTrail', 'CreateTrail', 'PutEventSelectors', 'DeleteEventSelectors')) SELECT eventTime, userIdentityarn, eventSource, eventName, awsRegion, sourceIPAddress, eventID, errorCode, errorMessage FROM cloudtrail_events ORDER BY eventTime DESC
```

Extra (returned, not expected):

- eventTime=`2019-04-17T16:30:09Z`, userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, eventSource=`cloudtrail.amazonaws.com`, eventName=`CreateTrail`, awsRegion=`us-east-1`, sourceIPAddress=`86.1.86.209`, eventID=`61c9e273-2c23-474e-b140-0ce9deb66ffa`, errorCode=`AccessDenied`, errorMessage=`User: arn:aws:iam::811596193553:user/Level6 is not authoriz…`
- eventTime=`2019-04-17T16:30:09Z`, userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, eventSource=`cloudtrail.amazonaws.com`, eventName=`CreateTrail`, awsRegion=`us-east-1`, sourceIPAddress=`86.1.86.209`, eventID=`61c9e273-2c23-474e-b140-0ce9deb66ffa`, errorCode=`AccessDenied`, errorMessage=`User: arn:aws:iam::811596193553:user/Level6 is not authoriz…`
- eventTime=`2019-02-11T16:43:38Z`, userIdentityarn=`arn:aws:sts::811596193553:assumed-role/AWSServiceRoleForClo…`, eventSource=`cloudtrail.amazonaws.com`, eventName=`CreateTrail`, awsRegion=`us-east-1`, sourceIPAddress=`cloudtrail.amazonaws.com`, eventID=`afa81985-bf03-4d04-8cf7-2d6bb60729fb`, errorCode=`ThrottlingException`, errorMessage=`Rate exceeded`

### 4. Unauthorized API Calls: scored

> **Answer-key note:** The hypothesis names AccessDenied and UnauthorizedOperation. With the real value Client.UnauthorizedOperation there are 2,679 (eventName, userIdentityarn) groups; the key has 2,387, close to AccessDenied alone (2,411), so some groups and counts cannot match.

Expected 2,387 groups, returned 1,500 (total 473,913, truncated): 1,372 matched, 1,015 missing, 128 extra. Matched on `eventName, userIdentityarn`.
API summary: 473,913 rows (first 10,000 shown; stats below cover those) · 115 distinct eventSource · 676 distinct eventName · 16 distinct awsRegion · eventTime 2020-09-11 → 2020-10-07

```sql
WITH unauthorized_api_calls AS (SELECT eventID, eventTime, eventSource, eventName, awsRegion, sourceIPAddress, userAgent, userIdentityarn, userIdentityuserName, errorCode, errorMessage, requestID FROM cloudtrail WHERE errorCode IN ('AccessDenied', 'AccessDeniedException', 'Client.UnauthorizedOperation') AND NOT errorCode IS NULL) SELECT eventID, eventTime, eventSource, eventName, awsRegion, sourceIPAddress, userAgent, userIdentityarn, userIdentityuserName, errorCode, errorMessage, requestID FROM unauthorized_api_calls ORDER BY CAST(eventTime AS TIMESTAMP) DESC
```

Missing (expected, not returned):

- eventName=`AddRoleToInstanceProfile`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`1`
- eventName=`AddUserToGroup`, userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, count=`3`
- eventName=`AssumeRole`, userIdentityarn=`arn:aws:iam::811596193553:user/SecurityMokey`, count=`53`

Extra (returned, not expected):

- eventName=`AttachVolume`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`null`
- eventName=`CreateDefaultVpc`, userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, count=`null`
- eventName=`CreateDefaultVpc`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, count=`null`

### 5. Whoami Reconnaissance: scored

Expected 4,767 groups, returned 2,720 (total 17,128, truncated): 2,720 matched, 2,047 missing, 0 extra. Matched on `userIdentityarn, sourceIPAddress, userAgent`.
API summary: 17,128 rows (first 10,000 shown; stats below cover those) · 1,987 distinct sourceIPAddress · 1,967 distinct userAgent · 1 distinct eventName · eventTime 2017-02-12 → 2019-08-22

```sql
WITH whoami_events AS (SELECT eventTime, sourceIPAddress, userAgent, eventName, eventSource, awsRegion, userIdentitytype, userIdentityaccountId, userIdentityprincipalId, userIdentityarn, userIdentityaccessKeyId, userIdentityuserName, errorCode, errorMessage FROM cloudtrail WHERE eventName = 'GetCallerIdentity') SELECT * FROM whoami_events ORDER BY CAST(eventTime AS TIMESTAMP)
```

Missing (expected, not returned):

- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, sourceIPAddress=`0.188.7.172`, userAgent=`Boto3/1.14.16 Python/3.8.3 Linux/5.6.0-kali2-amd64 Botocore…`, count=`27`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, sourceIPAddress=`0.188.7.172`, userAgent=`Boto3/1.9.106 Python/3.6.7 Linux/4.15.0-48-generic Botocore…`, count=`3`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, sourceIPAddress=`0.199.213.204`, userAgent=`aws-cli/1.18.26 Python/3.7.6 Linux/5.4.0-kali3-amd64 botoco…`, count=`1`

### 6. Secrets Manager Access: scored

Expected 1 rows, returned 398 (total 398): 1 matched, 0 missing, 397 extra. Matched on `eventID`.
API summary: 398 rows · 389 distinct eventID · 1 distinct eventSource · 2 distinct eventName · eventTime 2018-10-17 → 2020-10-07

```sql
WITH secrets_access AS (SELECT eventID, eventTime, eventSource, eventName, userIdentityarn, userIdentitytype, sourceIPAddress, userAgent, awsRegion, errorCode, errorMessage FROM cloudtrail WHERE eventSource = 'secretsmanager.amazonaws.com' AND (eventName LIKE '%GetSecretValue%' OR eventName LIKE '%DescribeSecret%' OR eventName LIKE '%ListSecrets%' OR eventName LIKE '%GetSecret%')) SELECT * FROM secrets_access ORDER BY CAST(eventTime AS TIMESTAMP) DESC
```

Extra (returned, not expected):

- eventID=`d36216c-2951-45cf-bab2-3eb582dd6985`, eventTime=`2020-10-07T08:09:14Z`, eventSource=`secretsmanager.amazonaws.com`, eventName=`ListSecrets`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, userIdentitytype=`IAMUser`, sourceIPAddress=`92.9.251.253`, userAgent=`Scout Suite/5.10.0 Python/3.7.3 Linux/4.4.0-039049-Microsof…`, awsRegion=`us-east-1`, errorCode=`AccessDenied`, errorMessage=`User: arn:aws:iam::811596193553:user/backup is not authoriz…`
- eventID=`7ab8bd26-eb63-4f3e-98ed-7e438da0b4b5`, eventTime=`2020-10-07T08:09:14Z`, eventSource=`secretsmanager.amazonaws.com`, eventName=`ListSecrets`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, userIdentitytype=`IAMUser`, sourceIPAddress=`92.9.251.253`, userAgent=`Scout Suite/5.10.0 Python/3.7.3 Linux/4.4.0-039049-Microsof…`, awsRegion=`us-east-2`, errorCode=`AccessDenied`, errorMessage=`User: arn:aws:iam::811596193553:user/backup is not authoriz…`
- eventID=`4b9f0027-e355-491e-ac25-8ab23d269f37`, eventTime=`2020-10-07T08:09:14Z`, eventSource=`secretsmanager.amazonaws.com`, eventName=`ListSecrets`, userIdentityarn=`arn:aws:iam::811596193553:user/backup`, userIdentitytype=`IAMUser`, sourceIPAddress=`92.9.251.253`, userAgent=`Scout Suite/5.10.0 Python/3.7.3 Linux/4.4.0-039049-Microsof…`, awsRegion=`us-west-1`, errorCode=`AccessDenied`, errorMessage=`User: arn:aws:iam::811596193553:user/backup is not authoriz…`

### 7. Large EC2 Instance Creation: scored

Expected 34 groups, returned 42 (total 300,622, truncated): 34 matched, 0 missing, 8 extra. Matched on `instanceType`.
API summary: 300,622 rows (first 10,000 shown; stats below cover those) · 1 distinct eventName · 1 distinct eventSource · 16 distinct awsRegion · eventTime 2019-08-23 → 2020-09-20

```sql
WITH filtered AS (SELECT eventID, eventTime, eventName, eventSource, awsRegion, sourceIPAddress, userIdentityarn, userIdentityuserName, userIdentityaccessKeyId, requestParametersinstanceType, errorCode, errorMessage, userAgent FROM cloudtrail WHERE eventName = 'RunInstances' AND (requestParametersinstanceType LIKE '%.10xlarge' OR requestParametersinstanceType LIKE '%.12xlarge' OR requestParametersinstanceType LIKE '%.16xlarge' OR requestParametersinstanceType LIKE '%.18xlarge' OR requestParametersinstanceType LIKE '%.24xlarge' OR requestParametersinstanceType LIKE '%.32xlarge' OR requestParametersinstanceType LIKE '%.metal')) SELECT eventID, eventTime, eventName, eventSource, awsRegion, sourceIPAddress, userIdentityarn, userIdentityuserName, requestParametersinstanceType, errorCode, errorMessage, userAgent FROM filtered ORDER BY CAST(eventTime AS TIMESTAMP) DESC
```

Extra (returned, not expected):

- instanceType=`c5.metal`, count=`null`
- instanceType=`c5d.metal`, count=`null`
- instanceType=`i3.metal`, count=`null`

### 8. S3 Bucket Brute Force: scored

> **Answer-key note:** The answer key keeps 212 of the 350 GetBucketAcl (actor, IP, user agent, error code) groups: failed requests only (AccessDenied, NoSuchBucket), and not all of those (the data has 270 failed-request groups). The hypothesis covers all attempts, so successful requests and the other failures count as extra.

Expected 163 groups, returned 67 (total 100): 42 matched, 121 missing, 25 extra. Matched on `userIdentityarn, sourceIPAddress`.
API summary: 100 rows · 61 distinct sourceIPAddress · 6 distinct userIdentityarn · 17 distinct userIdentityaccessKeyId

```sql
WITH s3_getbucketacl AS (SELECT eventTime, sourceIPAddress, userIdentityarn, userIdentityaccessKeyId, userIdentityuserName, awsRegion, errorCode, requestID FROM cloudtrail WHERE eventSource = 's3.amazonaws.com' AND eventName = 'GetBucketAcl') SELECT sourceIPAddress, userIdentityarn, userIdentityaccessKeyId, userIdentityuserName, awsRegion, COUNT(*) AS get_bucket_acl_attempts, COUNT(DISTINCT requestID) AS distinct_requests, MIN(CAST(eventTime AS TIMESTAMP)) AS first_seen, MAX(CAST(eventTime AS TIMESTAMP)) AS last_seen, ARRAY_AGG(DISTINCT errorCode) FILTER(WHERE NOT errorCode IS NULL) AS observed_error_codes FROM s3_getbucketacl GROUP BY sourceIPAddress, userIdentityarn, userIdentityaccessKeyId, userIdentityuserName, awsRegion ORDER BY get_bucket_acl_attempts DESC LIMIT 100
```

Missing (expected, not returned):

- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, sourceIPAddress=`0.188.7.172`, count=`10`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, sourceIPAddress=`101.217.125.255`, count=`1`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, sourceIPAddress=`106.250.42.115`, count=`4`

Extra (returned, not expected):

- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`250.251.253.3`, count=`null`
- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`252.1.22.60`, count=`null`
- userIdentityarn=`arn:aws:iam::811596193553:root`, sourceIPAddress=`255.253.125.115`, count=`null`

### 9a. Suspicious User Agents: scored

Expected 1,896 groups, returned 485 (total 156,930, truncated): 485 matched, 1,411 missing, 0 extra. Matched on `userIdentityarn, userAgent`.
API summary: 156,930 rows (first 10,000 shown; stats below cover those) · 254 distinct sourceIPAddress · 390 distinct userAgent · 298 distinct eventName · eventTime 2017-02-27 → 2020-01-14

```sql
SELECT eventTime, sourceIPAddress, userAgent, eventName, eventSource, userIdentityarn, userIdentityuserName, userIdentityaccountId, errorCode, awsRegion FROM cloudtrail WHERE userAgent ILIKE '%kali%' OR userAgent ILIKE '%parrot%' OR userAgent ILIKE '%powershell%'
```

Missing (expected, not returned):

- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, userAgent=`AWSPowerShell/226.1.255.1 .NET_Runtime/4.0 .NET_Framework/4…`, count=`74`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, userAgent=`AWSPowerShell/251.194.70.74 .NET_Runtime/4.0 .NET_Framework…`, count=`63`
- userIdentityarn=`arn:aws:iam::811596193553:user/Level6`, userAgent=`AWSPowerShell/252.6.234.251 .NET_Runtime/3.-1 .NET_Framewor…`, count=`37`

### 9b. Suspicious User Agents: scored

> **Answer-key note:** The answer key's userAgent values are the 'command/...' substring extracted from longer user-agent strings. No userAgent in the data starts with 'command/', so no query over the raw column can reproduce these groups.

Expected 101 groups, returned 535 (total 3,047): 0 matched, 101 missing, 535 extra. Matched on `userAgent`.
API summary: 3,047 rows · 97 distinct sourceIPAddress · 535 distinct userAgent · 99 distinct eventName · eventTime 2020-08-03 → 2020-10-07

```sql
WITH suspicious AS (SELECT eventID, eventTime, sourceIPAddress, userAgent, eventName, eventSource, awsRegion, userIdentityarn, userIdentityuserName, errorCode, requestID FROM cloudtrail WHERE userAgent ILIKE '%command/%') SELECT eventID, eventTime, sourceIPAddress, userAgent, eventName, eventSource, awsRegion, userIdentityarn, userIdentityuserName, errorCode, requestID FROM suspicious ORDER BY CAST(eventTime AS TIMESTAMP) DESC
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

Expected 40 rows, returned 40 (total 40): 40 matched, 0 missing, 0 extra. Matched on `sourceIPAddress, userIdentityarn`.
API summary: 40 rows · 32 distinct eventID · 3 distinct userIdentityarn · 3 distinct userIdentityuserName · eventTime 2017-03-01 → 2020-05-14

```sql
WITH iam_user_access_key_creation AS (SELECT eventID, eventTime, eventName, userIdentitytype, userIdentityarn, userIdentityuserName, sourceIPAddress, userAgent, awsRegion FROM cloudtrail WHERE eventName = 'CreateAccessKey' AND userIdentitytype = 'IAMUser') SELECT eventID, eventTime, userIdentityarn, userIdentityuserName, sourceIPAddress, userAgent, awsRegion FROM iam_user_access_key_creation ORDER BY CAST(eventTime AS TIMESTAMP) DESC
```

