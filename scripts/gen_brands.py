"""Write frontend/src/lib/brands.ts from Simple Icons (CC0) SVGs: path data + match words per brand.

    cd "$(mktemp -d)" && npm pack simple-icons && tar -xzf simple-icons-*.tgz
    python scripts/gen_brands.py <that dir>/package/icons frontend/src/lib/brands.ts <version>

To add a brand, add a (slug, words) row to BRANDS (slug = the SVG's file name) and run it again.
"""
import re, sys, pathlib, json
icons = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]); version = sys.argv[3]
# Order matters: the first brand whose word appears wins, so specific names come before general ones.
BRANDS = [
    ("netflix", ["netflix", "網飛"]),
    ("spotify", ["spotify"]),
    ("youtubemusic", ["youtube music", "yt music"]),
    ("youtube", ["youtube", "yt premium"]),
    ("applemusic", ["apple music"]),
    ("appletv", ["apple tv"]),
    ("icloud", ["icloud"]),
    ("apple", ["app store", "apple one", "apple"]),
    ("googledrive", ["google drive", "google one", "google 雲端"]),
    ("googleplay", ["google play"]),
    ("claude", ["claude"]),
    ("anthropic", ["anthropic"]),
    ("perplexity", ["perplexity"]),
    ("cursor", ["cursor"]),
    ("githubcopilot", ["copilot"]),
    ("github", ["github"]),
    ("notion", ["notion"]),
    ("figma", ["figma"]),
    ("dropbox", ["dropbox"]),
    ("evernote", ["evernote"]),
    ("todoist", ["todoist"]),
    ("1password", ["1password"]),
    ("bitwarden", ["bitwarden"]),
    ("nordvpn", ["nordvpn"]),
    ("expressvpn", ["expressvpn"]),
    ("surfshark", ["surfshark"]),
    ("protonvpn", ["protonvpn", "proton vpn"]),
    ("duolingo", ["duolingo", "多鄰國"]),
    ("zoom", ["zoom"]),
    ("discord", ["discord", "nitro"]),
    ("twitch", ["twitch"]),
    ("patreon", ["patreon"]),
    ("hbo", ["hbo"]),
    ("x", ["twitter", "x premium"]),
    ("telegram", ["telegram"]),
    ("line", ["line"]),
    ("steam", ["steam"]),
    ("playstation", ["playstation", "ps plus", "psn"]),
    ("ubereats", ["uber eats", "ubereats"]),
    ("uber", ["uber"]),
    ("foodpanda", ["foodpanda", "熊貓外送"]),
    ("grab", ["grab"]),
    ("starbucks", ["starbucks", "星巴克"]),
    ("mcdonalds", ["mcdonald", "麥當勞"]),
    ("kfc", ["kfc", "肯德基"]),
    ("ikea", ["ikea", "宜家"]),
    ("shopee", ["shopee", "蝦皮"]),
    ("airbnb", ["airbnb"]),
    ("bookingdotcom", ["booking.com", "booking"]),
    ("klook", ["klook"]),
    ("tesla", ["tesla", "特斯拉"]),
]
rows = []
for slug, words in BRANDS:
    svg = (icons / f"{slug}.svg").read_text()
    title = re.search(r"<title>(.*?)</title>", svg).group(1)
    d = re.search(r' d="([^"]+)"', svg).group(1)
    rows.append(f"  {json.dumps(slug)}: {{ title: {json.dumps(title, ensure_ascii=False)}, words: {json.dumps(words, ensure_ascii=False)}, d: {json.dumps(d)} }},")
out.write_text(f"""// Generated from Simple Icons {version} (https://simpleicons.org, CC0-1.0); only the brands listed here.
// The logos are their owners' trademarks, shown to tell subscriptions and shops apart in this local app.
// Regenerate with scripts/gen_brands.py when adding a brand.

/** Brand glyphs (24×24, one filled path) and the words in a note that mean that brand. */
export const BRANDS = {{
{chr(10).join(rows)}
}} as const satisfies Record<string, {{ title: string; words: readonly string[]; d: string }}>;

export type BrandSlug = keyof typeof BRANDS;

// Latin words must stand alone (so "line" is not found in "online"); Chinese words match anywhere.
const MATCHERS = (Object.keys(BRANDS) as BrandSlug[]).flatMap(slug =>
  BRANDS[slug].words.map(w => ({{
    slug,
    test: /^[\\x00-\\x7f]+$/.test(w)
      ? (s: string) => new RegExp(`(^|[^a-z0-9])${{w.replace(/[.+]/g, '\\\\$&')}}([^a-z0-9]|$)`).test(s)
      : (s: string) => s.includes(w),
  }})),
);

/** The brand a note or rule line names, if any: "Netflix 家庭方案" → netflix. */
export function brandOf(text: string | null | undefined): BrandSlug | null {{
  if (!text) return null;
  const s = text.normalize('NFKC').toLowerCase();
  return MATCHERS.find(m => m.test(s))?.slug ?? null;
}}
""")
print(len(rows), "brands")
