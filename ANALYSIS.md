# X.com (Twitter) 逆向侦察报告

> 目标：https://x.com/home
> 侦察时间：2026-06-04
> 登录状态：已登录（OAuth2Session）
> 账号：@toptips2024 (rest_id=1802912519155064832)

## 1. 平台概况

| 属性 | 值 |
|------|-----|
| 域名 | x.com / api.x.com / abs.twimg.com |
| 页面类型 | CSR (React SPA) |
| 数据协议 | GraphQL (queryId 路由) |
| 认证方式 | OAuth 2.0 Session + CSRF Token |
| CDN/WAF | Cloudflare |
| 服务端 | Cloudflare Envoy |
| JS 打包 | Webpack (client-web) |
| 视频 CDN | video.twimg.com (HLS + MP4) |
| 广告服务 | ads-api.x.com |

---

## 2. 认证体系

### 2.1 Bearer Token（公开常量）

```
Authorization: Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA
```

这是 X Web 客户端的公开 Bearer Token，硬编码在 JS bundle 中，对所有请求不变。**无需逆向**。

### 2.2 CSRF Token（ct0 cookie）

- Cookie 名：`ct0`
- Header 名：`x-csrf-token`
- 值相同，通常是服务端下发的 hex 字符串（如 `<ct0>`）
- 由服务端在首次访问时通过 Set-Cookie 下发
- 每次请求需在 Header 中携带相同值
- 生成机制：服务端生成，写入 cookie，JS 从 cookie 读取后写入 header

### 2.3 auth_token Cookie（HttpOnly）

- Cookie 名：`auth_token`
- 属性：**HttpOnly**（JS 无法通过 document.cookie 读取）
- 这是真正的登录凭据，由登录接口下发
- 格式：hex 字符串（如 `<auth_token>`）
- 所有 Authenticated 请求自动携带

### 2.4 其他 Cookie

| Cookie | 用途 | 动态 |
|--------|------|------|
| `guest_id` / `guest_id_marketing` / `guest_id_ads` | 匿名访客标识 | 首次访问生成，长期固定 |
| `gt` | 疑似 guest token | 服务端下发 |
| `personalization_id` | 个性化推荐 ID | 长期固定 |
| `twid` | 用户 ID 编码（`u%3D{rest_id}`）| 登录后设置 |
| `__cuid` | 客户端唯一 ID (UUID v4) | 本地生成 |
| `__cf_bm` | Cloudflare Bot Management | 动态（Cloudflare 管理） |
| `lang` | 语言偏好 | 固定（en） |
| `g_state` | Google Sign-In 状态 | 长期 |

### 2.5 必需请求头

```http
authorization: Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA
x-csrf-token: <从 ct0 cookie 获取>
x-twitter-active-user: yes
x-twitter-auth-type: OAuth2Session
x-twitter-client-language: en
x-client-transaction-id: <每次请求唯一生成>
content-type: application/json
```

### 2.6 x-client-transaction-id 生成

- 位置：`ondemand.s.{hash}.js`（按需加载，非 main bundle）
- 入口：`main.{hash}.js` 中 `s(host, path, method)` → 懒加载 chunk 调用其默认导出
- 由 feature flag `rweb_client_transaction_id_enabled` 控制
- **算法**：字符串数组混淆 + 读取首页 SVG 动画路径 + 三次贝塞尔曲线插值 + 密钥字节索引（来自 ondemand.js）
- 依赖 DOM：直接调用会因 `childNodes` 报错（需首页加载动画元素）
- 每次请求生成唯一值，格式为 ~94 字符 base64
- **不可省略**：缺失此头是被判定为自动化（错误码 226）的关键特征之一
- **实现**：因算法随 X 部署频繁变更，采用维护良好的 `x-client-transaction-id` 库还原，集成在 `utils/transaction_id.py` + `session_manager` httpx 请求钩子，自动注入 `/i/api/` 请求

---

## 3. GraphQL API 架构

### 3.1 路由格式

```
POST /i/api/graphql/{queryId}/{operationName}
GET  /i/api/graphql/{queryId}/{operationName}?variables={urlencoded_json}&features={urlencoded_json}
```

- `queryId`：大写字母+数字混合的 hash（如 `-M5P8LkjBRfeMF2MRJfbqA`）
- `operationName`：操作名（如 `HomeTimeline`、`UserByScreenName`）
- 所有 query ID 在 `main.4bcaea3a.js` webpack 模块中定义

### 3.2 核心 API 端点

| operationName | queryId | Method | 用途 |
|---------------|---------|--------|------|
| `HomeTimeline` | `-M5P8LkjBRfeMF2MRJfbqA` | POST | 主页时间线（For You） |
| `HomeLatestTimeline` | (待确认) | POST | 主页时间线（Following） |
| `UserByScreenName` | `IGgvgiOx4QZndDHuD3x9TQ` | GET | 通过 @用户名查用户 |
| `UserTweets` | `PNd0vlufvrcIwrAnBYKE9g` | GET | 用户推文列表 |
| `TweetDetail` | `6uCvnic3m5reVuehkvHa3w` | GET | 推文详情 |
| `SearchTimeline` (Bookmark) | `vctB13iDc4trZdZGzhNdVQ` | GET | 书签搜索 |
| `Followers` | `iYaPJI11EY8VtCL3hrKU9A` | GET | 粉丝列表 |
| `Following` | (待确认) | GET | 关注列表 |
| `FavoriteTweet` | `lI07N6Otwv1PhnEgXILM7A` | POST | 点赞推文 (mutation) |
| `CreateRetweet` | `mbRO74GrOvSfRcJnlMapnQ` | POST | 转推 (mutation) |
| `CreateTweet` | (待确认) | POST | 发推 (mutation) |
| `ExploreSidebar` | `CAIer_7yYdgfbPbmFxApJA` | GET | 侧边栏/趋势 |
| `SidebarUserRecommendations` | `Sujwk2Vj-pg3T8DvLKgWdw` | GET | 推荐关注 |
| `PinnedTimelines` | `SnNm4YWv4Xu26VSx-MIYlw` | GET | 置顶时间线 |
| `DataSaverMode` | `xF6sXnKJfS2AOylzxRjf6A` | GET | 省流量模式 |
| `getAltTextPromptPreference` | `PFIxTk8owMoZgiMccP0r4g` | GET | 图片描述偏好 |

### 3.3 REST API 端点

| URL | Method | 用途 |
|-----|--------|------|
| `api.x.com/1.1/account/settings.json` | GET | 用户设置 |
| `x.com/i/api/1.1/hashflags.json` | GET | 话题标签图标 |
| `x.com/i/api/2/badge_count/badge_count.json` | GET | 未读计数 |
| `x.com/i/api/fleets/v1/fleetline` | GET | 直播/音频空间 |
| `api.x.com/live_pipeline/events` | GET | 实时事件流 (SSE) |
| `x.com/i/api/1.1/graphql/user_flow.json` | POST | 用户行为埋点/分析 |

---

## 4. HomeTimeline 接口详解

### 4.1 首次请求（无 cursor）

```
POST https://x.com/i/api/graphql/-M5P8LkjBRfeMF2MRJfbqA/HomeTimeline
```

**Request Body:**
```json
{
  "variables": {
    "count": 20,
    "includePromotedContent": true,
    "requestContext": "launch",
    "withCommunity": true,
    "seenTweetIds": ["2062497596204073450", "2060329223957737644", "2062459573165056010", ...]
  },
  "features": { /* 37 个 feature flags */ },
  "queryId": "-M5P8LkjBRfeMF2MRJfbqA"
}
```

**关键参数：**
- `count`: 每页条数（默认 20）
- `requestContext`: 请求上下文（`launch` 首次 / 后续省略）
- `seenTweetIds`: 已看过的推文 ID 数组（避免重复）
- 首次请求无 `cursor`

### 4.2 分页请求（带 cursor）

```json
{
  "variables": {
    "count": 20,
    "cursor": "DAABCgABHJ-Cs3l__9sKAAIAAAAAAAAAAAgAAwAAAAIAAA",
    "includePromotedContent": true,
    "withCommunity": true,
    "seenTweetIds": ["2062482088037912822"]
  },
  "features": { /* 同上 */ },
  "queryId": "-M5P8LkjBRfeMF2MRJfbqA"
}
```

**分页机制：**
- cursor 从上一个响应的 `instructions[0].entries[]` 中提取
- cursor 来自 `TimelineTimelineCursor` entry，有 `Top` 和 `Bottom` 两种类型
- `Bottom` cursor 用于请求下一页
- 响应中包含 `cursorType: "Bottom"` 的 entry，其 `value` 即为下一页 cursor

### 4.3 响应结构

```
data.home.home_timeline_urt.instructions[0].entries[]
```

每个 entry 类型：
- `TimelineTimelineCursor` → cursor（分页标记）
- `TimelineTimelineItem` → 一条推文或广告

推文数据结构路径：
```
entry.itemContent.tweet_results.result
├── rest_id                      # 推文 ID
├── core.user_results.result     # 用户信息
│   ├── rest_id                  # 用户 ID
│   ├── legacy.screen_name       # @用户名
│   ├── legacy.name              # 显示名
│   ├── legacy.verified          # 是否认证
│   └── ...
├── legacy
│   ├── full_text                # 推文文本
│   ├── created_at               # 发布时间
│   ├── favorite_count           # 点赞数
│   ├── retweet_count            # 转推数
│   ├── reply_count              # 回复数
│   ├── quote_count              # 引用数
│   ├── bookmark_count           # 书签数
│   ├── entities                 # 话题标签/URL/提及/媒体
│   ├── lang                     # 语言
│   └── ...
├── views.count                  # 浏览量
├── source                       # 发推客户端
└── ...
```

### 4.4 广告推文识别

```json
"entry.itemContent.promotedMetadata": { /* 广告数据 */ }
```

通过 `itemContent.promotedMetadata` 存在与否判断是否为广告。

---

## 5. 风控分析

### 5.1 已确认的保护措施

| 机制 | 说明 | 难度 |
|------|------|------|
| Cloudflare WAF | 所有请求经过 CF | 低（正常 HTTP 即可通过） |
| CSRF Token | ct0 cookie + header | 低（首次访问自动获取） |
| Bearer Token | 公开常量，硬编码在 JS | 无 |
| Rate Limit | 500 req / 时间窗口 | 中（需控制频率） |
| auth_token | HttpOnly cookie | 中（需模拟登录或复用 cookie） |
| x-client-transaction-id | 每请求唯一 ID，缺失可能触发 226/404 | 低（已自动生成） |
| `__cf_bm` | Cloudflare Bot 检测 | 低（正常浏览器自动处理） |

### 5.2 未观察到的保护

- ❌ 无请求签名（sign/hmac）
- ❌ 无请求体加密
- ❌ 无响应加密
- ❌ 无设备指纹验证
- ❌ 无验证码（已验证登录态下）
- ❌ 无 navigator/webgl/canvas 环境检测

### 5.3 Rate Limit

```
x-rate-limit-limit: 500       # 每窗口最大请求数
x-rate-limit-remaining: 498   # 剩余请求数
x-rate-limit-reset: 1780576782 # 重置时间 (Unix timestamp)
```

`account/settings.json` 端点限制更严：100/窗口。

---

## 6. 采集方案建议

### 方案 A：纯 Python 复现（推荐）

**可行性：高**

1. 启动浏览器登录一次，导出 cookie（auth_token + ct0）
2. Python httpx/requests 复用 cookie
3. 直接调用 GraphQL API

**优点：**
- 无需浏览器环境
- 高并发友好
- 签名无依赖

**关键步骤：**
1. 获取 cookie（手动导出或 playwright 登录一次）
2. 构造 GraphQL 请求（Bearer token 硬编码）
3. 解析响应 JSON
4. cursor 分页遍历

### 方案 B：浏览器自动化

仅在 login 阶段用 playwright，采集阶段纯 HTTP。

---

## 7. 数据爬取要点

### 7.1 时间线采集循环

```python
cursor = None
while True:
    variables = {"count": 20, "includePromotedContent": True, "withCommunity": True}
    if cursor:
        variables["cursor"] = cursor
    
    resp = client.post(
        "https://x.com/i/api/graphql/-M5P8LkjBRfeMF2MRJfbqA/HomeTimeline",
        json={"variables": variables, "features": FEATURES, "queryId": "-M5P8LkjBRfeMF2MRJfbqA"}
    )
    
    data = resp.json()
    entries = data["data"]["home"]["home_timeline_urt"]["instructions"][0]["entries"]
    
    for entry in entries:
        if entry["content"]["entryType"] == "TimelineTimelineItem":
            tweet = entry["itemContent"]["tweet_results"]["result"]
            yield tweet  # 过滤 promotedMetadata 跳过广告
    
    # 找 Bottom cursor
    cursors = [e for e in entries if e["content"]["entryType"] == "TimelineTimelineCursor"
               and e["content"]["cursorType"] == "Bottom"]
    if not cursors:
        break
    cursor = cursors[0]["content"]["value"]
```

### 7.2 用户推文采集

```
GET https://x.com/i/api/graphql/PNd0vlufvrcIwrAnBYKE9g/UserTweets
  ?variables={"userId":"...","count":20,"cursor":null,...}
  &features={...}
```

---

## 8. 限制与风险

1. **auth_token 有效期**：登录态会过期，需定期刷新
2. **Rate Limit**：500/窗口，高频采集需控制 QPS
3. **Cloudflare 升级**：当前保护较宽松，X 可能随时加强
4. **queryId 变更**：Webpack bundle 更新时 queryId 可能变化（但变化频率低）
5. **仅限公开数据**：私密账号看不到、X Premium 内容受限

---

## 9. 关键文件记录

| 文件 | 说明 |
|------|------|
| `main.4bcaea3a.js` | 主 bundle，包含所有 GraphQL queryId 映射 |
| `bundle.HomeTimeline.63fed16a.js` | HomeTimeline 页面 bundle |
| `shared~bundle.HomeTimeline~loader.GetVerifiedSidebar.d0838a8a.js` | HomeTimeline 共享依赖 |

---

# VibeLoft Twitter/X 账号采集记录

> 目标：https://vibeloft.ai/
> 侦察时间：2026-07-21
> 登录状态：匿名公开访问

## 1. 结论

VibeLoft 是 React SPA，公开业务数据走 `https://api.vibeloft.ai/api/v1/` REST JSON 接口。当前未观察到请求签名、响应加密或浏览器绑定参数；普通 Python `httpx` 带 `Origin`、`Referer`、浏览器 UA 即可重放公开接口。

Twitter/X 账号记录在公开用户资料字段里：

```
POST /api/v1/user/list
GET  /api/v1/profiles/{username}
```

`user/list` 可分页枚举公开 profile，返回 `social_links`、`website`、`bio` 等字段。`profiles/{username}` 返回单个用户详情，字段同样包含 `profile.social_links`。

## 2. 接口证据

首页和产品页首轮网络请求包含：

```
GET /api/v1/rankings/cabin?activity_date=2026-07-20&limit=176
GET /api/v1/discovery/right-panel
GET /api/v1/products/{product_id}
GET /api/v1/products/{product_id}/discussion?page=1&page_size=20
```

profile 页请求：

```
GET /api/v1/profiles/chunxiangai
GET /api/v1/users/{profile_id}/timeline?tab=posts&limit=20
GET /api/v1/catalog/coding-tools?limit=500
```

`GET /api/v1/profiles/chunxiangai` 响应样例中可见：

```json
"social_links": [
  {
    "name": "Twitter/X",
    "platform": "twitter",
    "url": "https://x.com/chunxiangai"
  }
]
```

静态 bundle 常量包含：

```
USER.LIST = "user/list"
SOCIAL.PROFILE = "profiles/{username}"
RANKING.CABIN = "rankings/cabin"
PRODUCT.RANKING = "products/ranking"
FEED.LATEST = "feed/latest"
FEED.FOR_YOU = "feed/for-you"
```

js-reverse 发起栈确认产品详情请求由 `assets/index-04cef55cefc5-DGV7PtEg.js` 中的通用 HTTP client 发起，不是页面自动化或特殊 signer。

## 3. 当前采集结果

采集脚本：

```
uv run collect_vibeloft_twitter_accounts.py
```

输出文件：

```
data/vibeloft_twitter_accounts.json
```

2026-07-21 采集结果：

| 指标 | 数量 |
|------|------|
| VibeLoft profile 扫描数 | 1389 |
| Twitter/X 账号记录 | 76 |
| 去重 Twitter/X handle | 76 |
| `social_links.platform=twitter` 用户 | 73 |

采集逻辑：

1. `POST /api/v1/user/list`，`page_size=100`，按 `pagination.has_more` 翻页。
2. 从 `social_links` 中提取 `platform=twitter/x` 或 `x.com/twitter.com` URL。
3. 额外扫描 `website` 和 `bio` 中的 Twitter/X URL，避免用户把 X 链接填到非社交字段。
4. 兼容 `x.com/intent/follow?screen_name={handle}` 形式。
5. 规范化为 `https://x.com/{handle}`，按 VibeLoft profile id + handle 去重。

## 4. Twitter/X 侧统计

用户要求的“笔记”和“粉丝”按 Twitter/X 平台口径统计，而不是 VibeLoft 站内字段：

| Twitter/X 字段 | 含义 |
|----------------|------|
| `tweets` | X 主页 SSR 中的发帖/笔记数 |
| `followers` | X 主页 SSR 中的粉丝数 |
| `following` | X 主页 SSR 中的关注数 |

采集脚本：

```
uv run collect_twitter_profile_stats.py
```

输出文件：

```
data/vibeloft_twitter_x_stats.json
data/vibeloft_twitter_x_stats.csv
```

2026-07-21 针对 `social_links.platform=twitter` 的 73 个用户采集结果：

| 指标 | 数量 |
|------|------|
| 请求账号数 | 73 |
| 成功解析 | 73 |
| 失败 | 0 |
| X 侧总笔记数 | 212988 |
| X 侧总粉丝数 | 282895 |

实现方式：匿名请求 `https://x.com/{handle}`，从公开 SSR hydration 数据中解析 profile block 的 `followers`、`following`、`tweets`。该路径不依赖登录 cookie，也不使用浏览器自动化。
