import argparse
import json
import re
from collections import Counter, defaultdict

parser = argparse.ArgumentParser(description="Analyze an exported X/Twitter tweet JSON file.")
parser.add_argument("input", help="Path to a JSON file exported by user_tweets.py or search.py")
args = parser.parse_args()

d = json.load(open(args.input, encoding="utf-8"))
originals = [t for t in d if not t.get('is_retweet')]

print('='*60)
print(f'  推文内容分析: {args.input}')
print('='*60)

# 最热原创推文
print('\n【最热原创推文 Top 15 · 按点赞】')
top = sorted(originals, key=lambda t: t.get('favorite_count', 0), reverse=True)[:15]
for i, t in enumerate(top, 1):
    text = t['text'].replace('\n', ' ')[:120]
    print(f'{i:>2}. [{t["favorite_count"]:>5}♥ {t.get("views","?"):>8}👁] {text}')

# 最高曝光
print('\n【最高曝光推文 Top 10 · 按浏览量】')
top_v = sorted(originals, key=lambda t: int(t.get('views', 0) or 0), reverse=True)[:10]
for i, t in enumerate(top_v, 1):
    text = t['text'].replace('\n', ' ')[:120]
    views = int(t.get('views', 0) or 0)
    print(f'{i:>2}. [{views:>9}👁 {t["favorite_count"]:>5}♥] {text}')

# 关键词
print('\n【高频关键词 Top 40】')
all_text = ' '.join(t['text'] for t in originals).lower()
stripped = '.,!?()[]{}"\'":;'
words = [w.strip(stripped) for w in all_text.split() if len(w) > 3 and not w.startswith('http') and not w.startswith('@') and not w.startswith('#')]
stops = {'this','that','with','from','have','been','just','like','they','your','what','when','will','more','than','about','into','would','could','some','them','their','there','were','does','most','also','very','much','each','which','these','those','here','only','other','even','through','then','where','after','being','well','such','made','really','every','dont','think','want','know','things','thing','youre','its','im','cant','didnt','wasnt','hasnt','should','still','going','right','doing','actually','because','people','makes','something','someone','already','over','down','while','might','before','same','looks','since','using','isnt','whats','arent','came','took','sure','come','tell','need','been','able','got','her','she','him','his'}
freq = Counter(w for w in words if w not in stops and len(w) > 2)
for w, c in freq.most_common(40):
    print(f'  {c:>3}x  {w}')

# 语言分布
print('\n【推文语言分布】')
langs = Counter(t.get('lang','?') for t in originals)
for l, c in langs.most_common(10):
    print(f'  {l}: {c}')

# 月度分布
print('\n【月度发推分布】')
monthly = defaultdict(int)
for t in d:
    parts = t.get('created_at','').split()
    if len(parts) >= 6:
        monthly[f'{parts[5]}-{parts[1]}'] += 1
for ym in sorted(monthly.keys()):
    bar = '█' * (monthly[ym] // 3)
    print(f'  {ym}: {monthly[ym]:>3}  {bar}')

# 引用/转推对象
print('\n【引用/转推最多的账号 Top 15】')
targets = []
for t in d:
    text = t['text']
    for m in re.findall(r'RT @(\w+)', text):
        targets.append(m)
    for m in re.findall(r'@(\w+)', text[:100]):
        targets.append(m)
tc = Counter(targets)
for name, c in tc.most_common(15):
    print(f'  @{name}: {c}次')

# 分类主题（简单匹配）
print('\n【主题分类（关键词命中）】')
topics = {
    'AI/ML': ['ai', 'llm', 'gpt', 'claude', 'openai', 'anthropic', 'model', 'agent', 'prompt', 'chatgpt', 'gemini', 'deepseek', 'cursor', 'copilot'],
    '产品/工具': ['product', 'tool', 'app', 'launch', 'build', 'feature', 'ux', 'design', 'interface', 'saas'],
    '创业/商业': ['startup', 'founder', 'revenue', 'growth', 'market', 'business', 'fundraising', 'vc', 'company'],
    '编程/开发': ['code', 'coding', 'developer', 'api', 'python', 'javascript', 'github', 'open-source', 'framework', 'library'],
    '社交媒体/X': ['followers', 'twitter', 'x.com', 'tweet', 'thread', 'viral', 'engagement'],
    '生活方式': ['morning', 'coffee', 'travel', 'health', 'sleep', 'book', 'reading'],
}
for topic, kws in topics.items():
    count = sum(1 for t in originals if any(kw in t['text'].lower() for kw in kws))
    pct = count / len(originals) * 100 if originals else 0
    print(f'  {topic}: {count} 条 ({pct:.0f}%)')

# 媒体类型
print('\n【媒体附件】')
has_media = [t for t in originals if t.get('media')]
print(f'  含图片/视频的推文: {len(has_media)}/{len(originals)} ({len(has_media)/len(originals)*100:.0f}%)')
media_types = Counter()
for t in originals:
    for m in t.get('media', []):
        media_types[m.get('type','?')] += 1
for mt, c in media_types.most_common():
    print(f'  {mt}: {c}')
