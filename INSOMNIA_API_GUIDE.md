# Insomnia API Guide — Org Setup, Projects, Collections & Endpoint Templates

> **Audience:** Developers onboarding to a shared Insomnia organisation.
> **Insomnia version:** 9.x (Insomnia App + Insomnia Cloud Sync)

---

## Table of Contents

1. [Create & Configure Your Org Account](#1-create--configure-your-org-account)
2. [Create a Project](#2-create-a-project)
3. [Create a Collection (Document)](#3-create-a-collection-document)
4. [Environment & Variables Setup](#4-environment--variables-setup)
5. [Bearer Token Authentication](#5-bearer-token-authentication)
6. [Creating a GET Endpoint](#6-creating-a-get-endpoint)
7. [Creating a POST Endpoint](#7-creating-a-post-endpoint)
8. [SSL / TLS Settings](#8-ssl--tls-settings)
9. [Writing & Running Tests](#9-writing--running-tests)
10. [Endpoint Template Reference](#10-endpoint-template-reference)
11. [Importing Postman Collections](#11-importing-postman-collections)
12. [Naming Conventions & Best Practices](#12-naming-conventions--best-practices)

---

## 1. Create & Configure Your Org Account

### 1.1 Sign Up

```
https://app.insomnia.rest/signup
```

```
┌─────────────────────────────────────────────────────┐
│              insomnia  — Sign Up                    │
│                                                     │
│  Name      [ John Developer              ]          │
│  Email     [ john@company.com            ]          │
│  Password  [ ••••••••••••••             ]          │
│                                                     │
│           [ Create Account ]                        │
│                                                     │
│  Already have an account? Log in                    │
└─────────────────────────────────────────────────────┘
```

### 1.2 Create or Join an Organisation

After login you land on the **Dashboard**.

```
┌──────────────────────────────────────────────────────────────────┐
│  Insomnia Dashboard                              [+ New Org]     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Personal  │  My Org  │  + Create Organization           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  + New Org   │  │ Acme Corp ▶  │  │  Dev Team ▶  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

**Steps:**
1. Click **+ Create Organization** (top-right or centre card).
2. Enter **Organisation Name** → e.g. `Acme Corp`.
3. Choose plan → **Free** for small teams, **Team/Enterprise** for SSO & audit logs.
4. Click **Create**.

### 1.3 Invite Team Members

```
Org Settings → Members → [+ Invite Member]

┌──────────────────────────────────────────────────────┐
│  Invite Member                                       │
│                                                      │
│  Email     [ jane@company.com               ]       │
│  Role      [ Member ▼ ]  (Admin / Member)           │
│                                                      │
│            [ Send Invite ]                           │
└──────────────────────────────────────────────────────┘
```

| Role    | Permissions                                    |
|---------|------------------------------------------------|
| Admin   | Manage members, billing, all projects          |
| Member  | Create/edit collections inside assigned projects |

---

## 2. Create a Project

Projects are top-level containers inside an Org. One project per product/service is the recommended pattern.

```
Org Dashboard → [+ New Project]

┌──────────────────────────────────────────────────────┐
│  New Project                                         │
│                                                      │
│  Project Name  [ payments-service          ]         │
│  Type          (●) Cloud Sync  ( ) Local Only        │
│                                                      │
│               [ Create Project ]                     │
└──────────────────────────────────────────────────────┘
```

### Recommended Project Naming

| Pattern                        | Example                    |
|-------------------------------|----------------------------|
| `<team>-<service>`            | `platform-auth-service`    |
| `<product>-api`               | `mobile-app-api`           |
| `<client>-<env>-integration`  | `acme-staging-integration` |

---

## 3. Create a Collection (Document)

A **Collection** holds all requests for one API surface. A **Design Document** holds the OpenAPI spec. Most teams use Collections for day-to-day testing.

```
Project Dashboard → [+ Create] → Collection

┌──────────────────────────────────────────────────────┐
│  Create New Collection                               │
│                                                      │
│  Name    [ Payments API v2              ]            │
│                                                      │
│          [ Create ]                                  │
└──────────────────────────────────────────────────────┘
```

### Folder Structure Inside a Collection

```
📁 Payments API v2
 ├── 📁 Auth
 │    ├── POST  /auth/login
 │    └── POST  /auth/refresh
 ├── 📁 Payments
 │    ├── GET   /payments
 │    ├── GET   /payments/:id
 │    ├── POST  /payments
 │    └── DELETE /payments/:id
 ├── 📁 Webhooks
 │    └── POST  /webhooks/stripe
 └── 📁 Health
      └── GET   /health
```

**Create a folder:**
Right-click the collection name → **New Folder** → enter name.

---

## 4. Environment & Variables Setup

Environments let you switch between `local`, `staging`, and `production` without editing requests.

### 4.1 Open Environment Manager

```
Top bar → [No Environment ▼] → Manage Environments

┌──────────────────────────────────────────────────────────────────┐
│  Manage Environments                                             │
│  ┌──────────────────┐  ┌───────────────────────────────────┐   │
│  │ Base Environment │  │  {                                │   │
│  │ > Staging        │  │    "base_url": "...",             │   │
│  │ > Production     │  │    "api_version": "v2"            │   │
│  │ [+ Add]          │  │  }                                │   │
│  └──────────────────┘  └───────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Base Environment (shared variables)

```json
{
  "api_version": "v2",
  "timeout": 30000
}
```

### 4.3 Sub-Environments

**Local**
```json
{
  "base_url": "http://localhost:3000",
  "bearer_token": "local-dev-token-abc123"
}
```

**Staging**
```json
{
  "base_url": "https://api-staging.company.com",
  "bearer_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Production**
```json
{
  "base_url": "https://api.company.com",
  "bearer_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### 4.4 Reference Variables in Requests

Use `{{ variable_name }}` anywhere in URL, headers, or body:

```
{{ base_url }}/{{ api_version }}/payments
```

---

## 5. Bearer Token Authentication

### 5.1 Collection-Level Auth (applies to all requests)

```
Collection → Right-click → Edit → Auth tab

┌──────────────────────────────────────────────────────┐
│  Collection Auth                                     │
│                                                      │
│  Auth Type  [ Bearer Token ▼ ]                      │
│  Token      [ {{ bearer_token }}         ]           │
│  Prefix     [ Bearer              ]  (default)       │
│                                                      │
│             [ Save ]                                 │
└──────────────────────────────────────────────────────┘
```

> Setting auth at the **collection level** automatically adds `Authorization: Bearer <token>` to every request. Individual requests can override this.

### 5.2 Request-Level Auth Override

```
Request → Auth tab

┌──────────────────────────────────────────────────────┐
│  Auth                                                │
│                                                      │
│  Auth Type  [ Bearer Token ▼ ]                      │
│  Token      [ eyJhbGci...                ]           │
│                                                      │
│  [ ] Inherit from collection                         │
└──────────────────────────────────────────────────────┘
```

### 5.3 Auto-Fetch Token via Login Request

1. Create `POST /auth/login` request (see Section 7).
2. Go to **Tests** tab on the login request:

```javascript
const json = await response.json();
insomnia.setEnvironmentVariable("bearer_token", json.data.token);
```

3. Every time you run the login request, `bearer_token` is updated automatically.

### 5.4 Auth Header Preview

After setting up, the **Header** tab shows:
```
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 6. Creating a GET Endpoint

### 6.1 New Request

```
Folder → [+] → New HTTP Request

┌──────────────────────────────────────────────────────────────────────┐
│  [GET ▼]  [ {{ base_url }}/{{ api_version }}/payments       ] [Send] │
│  ──────────────────────────────────────────────────────────────────  │
│  Params │ Auth │ Headers │ Docs │ Tests                              │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 Query Parameters Tab

```
Params tab → [+ Add Parameter]

┌──────────────────────────────────────────┐
│  Query Parameters                        │
│                                          │
│  ☑  page      [ 1         ]             │
│  ☑  limit     [ 20        ]             │
│  ☑  status    [ active    ]             │
│  ☐  cursor    [           ]  (disabled) │
│                                          │
│  [+ Add]                                 │
└──────────────────────────────────────────┘
```

This builds: `?page=1&limit=20&status=active`

### 6.3 Headers Tab

```
Headers tab

┌────────────────────────────────────────────────────┐
│  Name                   Value                      │
│  ─────────────────────────────────────────────── │
│  Accept                 application/json           │
│  Content-Type           application/json           │
│  X-Request-ID           {{ $uuid }}                │
│  X-Client-Version       2.0.0                      │
└────────────────────────────────────────────────────┘
```

### 6.4 Full GET Request Example

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Method      | `GET`                                              |
| URL         | `{{ base_url }}/{{ api_version }}/payments/{{id}}`|
| Auth        | Bearer `{{ bearer_token }}`                        |
| Accept      | `application/json`                                 |
| X-Request-ID| `{{ $uuid }}`                                      |

---

## 7. Creating a POST Endpoint

### 7.1 New Request

```
Folder → [+] → New HTTP Request → change method to POST

┌──────────────────────────────────────────────────────────────────────┐
│  [POST ▼]  [ {{ base_url }}/{{ api_version }}/payments      ] [Send] │
│  ──────────────────────────────────────────────────────────────────  │
│  Body │ Auth │ Headers │ Params │ Docs │ Tests                       │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.2 Body Tab — JSON

```
Body tab → [JSON ▼]

┌──────────────────────────────────────────────────────┐
│  Body  [JSON ▼]                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ {                                              │  │
│  │   "amount": 5000,                              │  │
│  │   "currency": "usd",                           │  │
│  │   "description": "Order #1042",               │  │
│  │   "customer_id": "{{ customer_id }}",          │  │
│  │   "metadata": {                                │  │
│  │     "order_id": "1042",                        │  │
│  │     "source": "mobile"                         │  │
│  │   }                                            │  │
│  │ }                                              │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 7.3 Body Tab — Form Data (multipart)

```
Body tab → [Multipart Form ▼]

┌───────────────────────────────────────────────────────┐
│  Name           Value              Type               │
│  ─────────────────────────────────────────────────── │
│  username       john@company.com   Text               │
│  password       {{ password }}     Text               │
│  avatar         [Choose File]      File               │
└───────────────────────────────────────────────────────┘
```

### 7.4 Full POST Login Example

| Field        | Value                                        |
|--------------|----------------------------------------------|
| Method       | `POST`                                       |
| URL          | `{{ base_url }}/{{ api_version }}/auth/login`|
| Content-Type | `application/json`                           |
| Auth         | None (public endpoint)                       |
| Body         | `{ "email": "...", "password": "..." }`      |

---

## 8. SSL / TLS Settings

### 8.1 Global SSL Settings

```
Preferences (Ctrl+,) → Security

┌──────────────────────────────────────────────────────┐
│  Security & SSL                                      │
│                                                      │
│  [ ] Validate SSL Certificates  ← uncheck for local │
│  [ ] Send cookies automatically                      │
│  [✓] Follow redirects                               │
│                                                      │
│  Client Certificates  [+ Add Certificate]            │
└──────────────────────────────────────────────────────┘
```

> **Warning:** Only disable SSL validation in local/dev environments. **Never** disable for staging or production.

### 8.2 Per-Request SSL Override

```
Request → Settings (gear icon) → SSL

┌──────────────────────────────────────────────────────┐
│  Request Settings                                    │
│                                                      │
│  HTTP version    [ HTTP/1.1 ▼ ]                     │
│  Validate certs  [✓] Enabled                        │
│  Follow redirects [✓] Enabled                       │
│  Max redirects   [ 10         ]                     │
└──────────────────────────────────────────────────────┘
```

### 8.3 Add a Client Certificate (mTLS)

```
Preferences → Security → Client Certificates → [+ Add Certificate]

┌──────────────────────────────────────────────────────┐
│  Add Client Certificate                              │
│                                                      │
│  Host       [ api.company.com          ]            │
│  PFX/P12    [ Browse... ] client.p12                │
│    — OR —                                            │
│  CRT File   [ Browse... ] client.crt                │
│  Key File   [ Browse... ] client.key                │
│  Passphrase [ ••••••••••             ]              │
│                                                      │
│             [ Add Certificate ]                      │
└──────────────────────────────────────────────────────┘
```

### 8.4 Add a Custom CA Certificate

```
Preferences → Security → CA Certificates → [+ Add CA]

┌──────────────────────────────────────────────────────┐
│  CA Certificate                                      │
│                                                      │
│  PEM File   [ Browse... ] my-company-ca.pem          │
│                                                      │
│             [ Add ]                                  │
└──────────────────────────────────────────────────────┘
```

### 8.5 SSL Quick-Reference

| Scenario                          | Setting                                   |
|-----------------------------------|-------------------------------------------|
| Self-signed cert (local dev)      | Disable SSL validation (Preferences)      |
| Internal CA cert (staging)        | Add custom CA in Preferences              |
| Mutual TLS (mTLS)                 | Add client cert (PFX or CRT+KEY)         |
| Production public cert            | Keep validation enabled (default)         |

---

## 9. Writing & Running Tests

### 9.1 Open Tests Tab

```
Request → Tests tab

┌──────────────────────────────────────────────────────────────────┐
│  Tests                                           [▶ Run Tests]   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  const response = await insomnia.send();                  │  │
│  │                                                            │  │
│  │  expect(response.status).toBe(200);                       │  │
│  │                                                            │  │
│  │  const json = await response.json();                      │  │
│  │  expect(json).toHaveProperty('data');                     │  │
│  │  expect(json.data).toBeArray();                           │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 9.2 Common Test Snippets

**Status code check**
```javascript
expect(response.status).toBe(200);
```

**Response time**
```javascript
expect(response.headers.get('X-Response-Time')).toBeLessThan(500);
```

**JSON body structure**
```javascript
const json = await response.json();
expect(json).toHaveProperty('data');
expect(json.data.id).toBeDefined();
expect(typeof json.data.amount).toBe('number');
```

**Save token from login response**
```javascript
const json = await response.json();
insomnia.setEnvironmentVariable("bearer_token", json.data.token);
insomnia.setEnvironmentVariable("user_id", json.data.user.id);
```

**Check header exists**
```javascript
expect(response.headers.get('Content-Type')).toContain('application/json');
```

**Array not empty**
```javascript
const json = await response.json();
expect(json.data.length).toBeGreaterThan(0);
```

### 9.3 Test Results Panel

```
┌────────────────────────────────────────────────────────┐
│  Test Results                                          │
│                                                        │
│  ✅  Status is 200                             0.3 ms  │
│  ✅  Response has 'data' property              0.1 ms  │
│  ✅  data is an array                          0.1 ms  │
│  ❌  data.length > 0                           FAILED  │
│       Expected: > 0  Received: 0                       │
└────────────────────────────────────────────────────────┘
```

### 9.4 Run Collection Tests (Test Suite)

```
Collection → [▶ Run Tests]  (or Ctrl+Shift+Enter)

┌──────────────────────────────────────────────────────────────────┐
│  Test Suite Runner                                               │
│                                                                  │
│  Select Requests:                                                │
│  ☑  POST /auth/login           ☑  GET  /payments                │
│  ☑  POST /payments             ☐  DELETE /payments/:id          │
│                                                                  │
│  Environment: [ Staging ▼ ]   Delay: [ 200ms ]                  │
│                                                                  │
│                              [ Run ]                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. Endpoint Template Reference

Use the following as copy-paste templates for your collection folders.

### 10.1 Auth Endpoints

| Name                  | Method | Path                            | Body                                     | Auth   |
|-----------------------|--------|---------------------------------|------------------------------------------|--------|
| Login                 | POST   | `/v2/auth/login`                | `{ email, password }`                    | None   |
| Refresh Token         | POST   | `/v2/auth/refresh`              | `{ refresh_token }`                      | None   |
| Logout                | POST   | `/v2/auth/logout`               | —                                        | Bearer |
| Get Current User      | GET    | `/v2/auth/me`                   | —                                        | Bearer |
| Change Password       | PATCH  | `/v2/auth/password`             | `{ current_password, new_password }`     | Bearer |

### 10.2 Resource CRUD Template

Replace `{resource}` with your resource name (e.g. `payments`, `users`, `orders`).

| Name                  | Method | Path                            | Body                    | Auth   |
|-----------------------|--------|---------------------------------|-------------------------|--------|
| List {resource}       | GET    | `/v2/{resource}`                | —                       | Bearer |
| Get {resource}        | GET    | `/v2/{resource}/{{id}}`         | —                       | Bearer |
| Create {resource}     | POST   | `/v2/{resource}`                | Resource JSON payload   | Bearer |
| Update {resource}     | PUT    | `/v2/{resource}/{{id}}`         | Resource JSON payload   | Bearer |
| Patch {resource}      | PATCH  | `/v2/{resource}/{{id}}`         | Partial JSON payload    | Bearer |
| Delete {resource}     | DELETE | `/v2/{resource}/{{id}}`         | —                       | Bearer |

### 10.3 Standard Request Headers Template

Add to every request or set at collection level:

```
Accept:           application/json
Content-Type:     application/json
Authorization:    Bearer {{ bearer_token }}
X-Request-ID:     {{ $uuid }}
X-Client-Version: 1.0.0
X-Org-ID:         {{ org_id }}
```

### 10.4 Standard Response Assertions Template

```javascript
// Paste this in the Tests tab of any request
const json = await response.json();

// 1. Status
expect(response.status).toBe(200);  // change per endpoint

// 2. Content-Type
expect(response.headers.get('Content-Type')).toContain('application/json');

// 3. Envelope structure
expect(json).toHaveProperty('success');
expect(json).toHaveProperty('data');

// 4. No unexpected errors
expect(json.error).toBeUndefined();
```

---

## 11. Importing Postman Collections

### 11.1 Export from Postman

```
Postman → Your Collection → ··· (three dots) → Export

┌────────────────────────────────────────────────────┐
│  Export Collection                                 │
│                                                    │
│  Select format:                                    │
│  (●) Collection v2.1  ← recommended               │
│  ( ) Collection v2.0                               │
│                                                    │
│              [ Export ]                            │
└────────────────────────────────────────────────────┘
```

Save as `my-collection.postman_collection.json`.

**Also export your Postman Environments:**
```
Postman → Environments → ··· → Export → Save as .json
```

### 11.2 Import into Insomnia

```
Insomnia → Project Dashboard → [Import ▼]

┌──────────────────────────────────────────────────────┐
│  Import Data                                         │
│                                                      │
│  (●) From File                                       │
│  ( ) From URL                                        │
│  ( ) From Clipboard                                  │
│                                                      │
│  [ Browse... ]  my-collection.postman_collection.json│
│                                                      │
│  Import as: (●) Collection  ( ) Design Document      │
│                                                      │
│              [ Import ]                              │
└──────────────────────────────────────────────────────┘
```

Insomnia auto-detects Postman v2.0/v2.1 and OpenAPI formats.

### 11.3 What Gets Migrated

| Postman Feature         | Insomnia Equivalent              | Migrated? |
|-------------------------|----------------------------------|-----------|
| Collections             | Collections                      | ✅ Yes    |
| Folders                 | Folders                          | ✅ Yes    |
| Requests (GET/POST/etc) | Requests                         | ✅ Yes    |
| Headers                 | Headers                          | ✅ Yes    |
| Body (JSON, Form)       | Body                             | ✅ Yes    |
| Query Params            | Query Params                     | ✅ Yes    |
| Pre-request Scripts     | Pre-request Scripts (JS)         | ✅ Yes    |
| Test Scripts            | Tests (JS)                       | ✅ Yes    |
| Environment Variables   | Environment Variables            | ✅ Yes    |
| `pm.environment.set`    | `insomnia.setEnvironmentVariable`| ⚠️ Manual |
| `pm.test`               | `expect` (Jest-style)            | ⚠️ Manual |
| OAuth 2.0               | OAuth 2.0                        | ✅ Yes    |
| Bearer Token Auth       | Bearer Token Auth                | ✅ Yes    |
| Collection Variables    | Base Environment                 | ✅ Yes    |

### 11.4 Fix Postman Script Syntax

After import, update any Postman-specific API calls:

| Postman                                        | Insomnia                                               |
|------------------------------------------------|--------------------------------------------------------|
| `pm.environment.set("key", value)`             | `insomnia.setEnvironmentVariable("key", value)`        |
| `pm.environment.get("key")`                    | `insomnia.environment.get("key")`                      |
| `pm.response.json()`                           | `await response.json()`                                |
| `pm.response.code`                             | `response.status`                                      |
| `pm.test("name", fn)`                          | `expect(...)` — Jest-style                             |
| `pm.expect(val).to.eql(other)`                 | `expect(val).toBe(other)`                              |

### 11.5 Import OpenAPI / Swagger

```
Import → From File → Select your openapi.yaml or swagger.json

Insomnia will:
  ✅ Create a Design Document with the spec
  ✅ Generate a matching Collection with all endpoints
  ✅ Pre-fill URL paths, query params, and body schemas
```

---

## 12. Naming Conventions & Best Practices

### 12.1 Project Names

```
<team>-<service>-api
<product>-<environment>
```

Examples:
- `platform-auth-api`
- `ecommerce-checkout-api`
- `mobile-push-notifications`
- `acme-client-staging`

### 12.2 Collection Names

```
<Service Name> API  v<major>
```

Examples:
- `Payments API v2`
- `User Service API v1`
- `Notification API v3`

### 12.3 Folder Names

Use the **resource or feature name** in PascalCase or Title Case:

```
📁 Authentication
📁 Users
📁 Payments
📁 Webhooks
📁 Admin
📁 Health & Monitoring
```

### 12.4 Request Names

Use the format: `[HTTP Method] — Description`

```
GET  — List Payments
GET  — Get Payment by ID
POST — Create Payment
PUT  — Update Payment
DEL  — Delete Payment
POST — Login
POST — Refresh Token
```

### 12.5 Environment Names

```
Local       → http://localhost:3000
Development → https://api-dev.company.com
Staging     → https://api-staging.company.com
Production  → https://api.company.com
```

### 12.6 Variable Naming

Use `snake_case` for all environment variables:

```json
{
  "base_url": "...",
  "bearer_token": "...",
  "api_version": "v2",
  "org_id": "...",
  "user_id": "...",
  "customer_id": "...",
  "payment_id": "..."
}
```

### 12.7 Git Sync (Team Collaboration)

```
Collection → ··· → Setup Git Sync

┌──────────────────────────────────────────────────────┐
│  Git Sync                                            │
│                                                      │
│  Repository URL                                      │
│  [ https://github.com/org/insomnia-collections ]    │
│                                                      │
│  Author Name   [ John Developer      ]              │
│  Author Email  [ john@company.com    ]              │
│                                                      │
│  Token         [ ghp_xxxxxxxxxxxx    ]              │
│                                                      │
│                [ Connect ]                           │
└──────────────────────────────────────────────────────┘
```

> Commit collection changes like code: branch per feature, PR to main.

---

## Quick-Start Checklist

```
□  1. Create Insomnia account at app.insomnia.rest
□  2. Create or join your Organisation
□  3. Invite team members with correct roles
□  4. Create a Project using naming convention
□  5. Create a Collection inside the Project
□  6. Set up Base Environment + sub-environments (Local, Staging, Prod)
□  7. Add bearer_token and base_url to each environment
□  8. Configure Collection-level Bearer Token auth
□  9. Add SSL client certificates if using mTLS
□ 10. Create Auth folder → POST /auth/login with token-save test
□ 11. Create resource folders using CRUD template
□ 12. Add standard headers to each request
□ 13. Write response assertion tests on each endpoint
□ 14. Import existing Postman collections if migrating
□ 15. Fix any pm.* → insomnia.* script migrations
□ 16. Set up Git Sync for team version control
```

---

*Last updated: March 2026 — Insomnia 9.x*
