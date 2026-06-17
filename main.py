#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_PATH = DATA_DIR / "state.json"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_REPORT_HOUR = int(os.environ.get("REPORT_HOUR", "9"))
DEFAULT_REPORT_MINUTE = int(os.environ.get("REPORT_MINUTE", "20"))
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TRANSLATION_CACHE_LOCK = threading.Lock()
REMOTE_TRANSLATION_ENABLED = os.environ.get("ENABLE_REMOTE_TRANSLATION", "1").lower() in {
    "1",
    "true",
    "yes",
}
ENGLISH_OUTPUT_MODE = os.environ.get("ENGLISH_OUTPUT_MODE", "").lower() in {
    "1",
    "true",
    "yes",
}
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "").strip()
DEEPL_API_URL = os.environ.get("DEEPL_API_URL", "https://api-free.deepl.com/v2/translate")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", os.environ.get("LLM_API_KEY", "")).strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", os.environ.get("LLM_BASE_URL", "")).strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", os.environ.get("LLM_MODEL", "")).strip()
OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "45"))
ARTICLE_EXCERPT_LIMIT = 1400


SECTION_TITLES = {
    "head_releases": "头部发行",
    "music_ai_industry": "AI·产业动向",
    "music_news": "补位音乐资讯",
    "holiday_events": "节庆预警",
    "social_trends": "社媒热点",
    "culture_art": "文化·艺术界",
    "politics": "国际政坛",
    "ops_suggestions": "运营建议",
}


REPORT_SECTION_ORDER = [
    "head_releases",
    "music_ai_industry",
    "social_trends",
    "culture_art",
    "politics",
    "holiday_events",
    "ops_suggestions",
]


SECTION_LIMITS = {
    "head_releases": 6,
    "music_ai_industry": 6,
    "social_trends": 6,
    "culture_art": 6,
    "politics": 6,
    "ops_suggestions": 0,  # 由 generate_action_plan 填充，不走 RSS 通道
}


SECTION_MIN_COUNTS = {
    "head_releases": 3,
    "music_ai_industry": 3,  # 新增：确保 AI 产业动向每天至少 3 条
    "social_trends": 3,
    "culture_art": 3,  # 从 2 提升到 3
    "politics": 3,
}


SECTION_MIN_BUSINESS_SCORES = {
    "head_releases": 3.0,
    "music_ai_industry": 1.0,  # 从 3.0 降低，放宽 AI 产业动向入选门槛
    "social_trends": 2.0,  # 从 3.2 降低，允许更多社媒事件
    "culture_art": 1.0,
    "politics": 0.0,  # 政治新闻直接放行，不要求业务相关
}


MAX_REPORT_ITEMS = 36


COUNTRY_NAMES = {
    "GB": "英国",
    "FR": "法国",
    "DE": "德国",
    "IT": "意大利",
    "ES": "西班牙",
    "ID": "印度尼西亚",
    "PH": "菲律宾",
    "MY": "马来西亚",
    "US": "美国",
    "CA": "加拿大",
    "AU": "澳大利亚",
    "NZ": "新西兰",
    "JP": "日本",
    "KR": "韩国",
    "IN": "印度",
    "TH": "泰国",
    "VN": "越南",
    "SG": "新加坡",
    "BR": "巴西",
    "MX": "墨西哥",
    "AR": "阿根廷",
    "CO": "哥伦比亚",
    "CL": "智利",
    "PE": "秘鲁",
    "NG": "尼日利亚",
    "ZA": "南非",
    "EG": "埃及",
    "KE": "肯尼亚",
    "GH": "加纳",
    "SA": "沙特阿拉伯",
    "AE": "阿联酋",
    "TR": "土耳其",
    "PL": "波兰",
    "NL": "荷兰",
    "SE": "瑞典",
    "NO": "挪威",
    "DK": "丹麦",
    "FI": "芬兰",
    "PT": "葡萄牙",
    "UA": "乌克兰",
    "RO": "罗马尼亚",
    "HU": "匈牙利",
    "CZ": "捷克",
    "AT": "奥地利",
    "CH": "瑞士",
    "BE": "比利时",
    "GR": "希腊",
    "IL": "以色列",
    "PK": "巴基斯坦",
    "BD": "孟加拉国",
}


HEAD_RELEASE_INCLUDE = [
    "single",
    "song",
    "track",
    "album",
    "ep",
    "lp",
    "mixtape",
    "music video",
    "video",
    "visual",
    "teaser",
    "trailer",
    "out now",
    "released",
    "release",
    "pre-order",
    "preorder",
    "pre-save",
    "presave",
    "debut",
    "tour",
    "tour dates",
    "festival",
    "lineup",
    "live show",
    "live performance",
    "live debut",
    "premiere",
    "setlist",
    "playlist",
    "listening party",
    "listening experience",
]

HEAD_RELEASE_EXCLUDE = [
    "financial result",
    "buyback",
    "acquire",
    "acquisition",
    "deal",
    "publishing deal",
    "distribution partnership",
    "partnership",
    "appoints",
    "appointed",
    "elevated",
    "evp",
    "earnings",
    "podcast",
    "initiative",
    "foundation",
    "school",
    "conference call",
    "share buyback",
    "quarter",
    "revenue",
    "investor",
    "documentary",
]

HEAD_RELEASE_MEDIA_INCLUDE = [
    "new album",
    "album",
    "single",
    "new song",
    "music video",
    "video",
    "mv",
    "visual",
    "release date",
    "out now",
    "drops",
    "drop",
    "release",
    "releases",
    "announces",
    "announce",
    "coming",
    "debut",
    "teaser",
    "trailer",
    "pre-save",
    "tour",
    "tour dates",
    "festival",
    "lineup",
    "live show",
    "live performance",
    "live debut",
    "premiere",
    "setlist",
    "playlist",
    "listening party",
    "listening experience",
]

HEAD_RELEASE_PRIORITY_ARTISTS = [
    "sabrina carpenter",
    "lady gaga",
    "olivia rodrigo",
    "doechii",
    "billie eilish",
    "dua lipa",
    "taylor swift",
    "the weeknd",
    "bad bunny",
    "karol g",
    "drake",
    "ariana grande",
    "post malone",
    "kendrick lamar",
    "travis scott",
    "bts",
    "jennie",
    "rihanna",
    "ed sheeran",
    "coldplay",
    "shakira",
    "harry styles",
    "rosalia",
    "morgan wallen",
    "charli xcx",
    "the strokes",
    "iceage",
]

SOCIAL_KEYWORDS = [
    "meme",
    "viral",
    "tiktok",
    "instagram",
    "youtube",
    "challenge",
    "creator",
    "trend",
    "fandom",
    "stan",
    "reels",
    "shorts",
    "celebrity",
    "concert",
    "drama",
    "beef",
    "feud",
    "cancel",
    "controversy",
    "backlash",
    "reaction",
    "reddit",
    "twitter",
    "x.com",
    "going viral",
    "fan",
    "debate",
    "discourse",
    "cringe",
    "wholesome",
    "ratio",
]

AI_INDUSTRY_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "music tech",
    "streaming",
    "subscription",
    "pricing",
    "price",
    "royalty",
    "rights",
    "licensing",
    "audio",
    "distribution",
    "platform",
    "catalog",
    "startup",
    "generator",
]

POLITICS_KEYWORDS = [
    "president",
    "prime minister",
    "election",
    "congress",
    "senate",
    "parliament",
    "supreme court",
    "war",
    "ukraine",
    "tariff",
    "immigration",
    "nato",
    "white house",
    "eu",
    "minister",
    "government",
    "policy",
    "diplomacy",
    "summit",
    "sanctions",
    "military",
    "conflict",
    "ceasefire",
    "protest",
    "referendum",
    "vote",
    "law",
    "legislation",
    "court",
    "ruling",
    "treaty",
    "un",
    "united nations",
    "crisis",
    "invasion",
    "nuclear",
    "allies",
    "bilateral",
    "geopolitics",
    "cabinet",
    "governor",
    "mayor",
    "diplomat",
    "foreign",
    "g7",
    "g20",
    "imf",
    "world bank",
    "opec",
    "trump",
    "biden",
    "macron",
    "modi",
    "putin",
    "xi",
]

CULTURE_KEYWORDS = [
    "film",
    "movie",
    "cinema",
    "theater",
    "theatre",
    "tv",
    "series",
    "showrunner",
    "streaming series",
    "festival",
    "cannes",
    "sundance",
    "venice",
    "berlin",
    "toronto",
    "tribeca",
    "sxsw",
    "locarno",
    "miffest",
    "soccer",
    "football",
    "art",
    "artist",
    "gallery",
    "museum",
    "exhibition",
    "installation",
    "contemporary art",
    "trailer",
    "teaser",
    "adaptation",
    "prequel",
    "sequel",
    "remake",
    "reboot",
    "documentary",
    "animation",
    "anime",
    "horror",
    "sci-fi",
    "fantasy",
    "director",
    "filmmaker",
    "actor",
    "actress",
    "cast",
    "screenwriter",
    "producer",
    "auteur",
    "franchise",
    "video game adaptation",
    "letterboxd",
    "soundtrack",
    "score",
    "composer",
    "box office",
]


BUSINESS_CORE_KEYWORDS = [
    "ai music",
    "ai-generated",
    "aigc",
    "generative ai",
    "artificial intelligence",
    "music video",
    "ai video",
    "text-to-video",
    "suno",
    "udio",
    "runway",
    "pika",
    "luma",
    "kling",
    "elevenlabs",
    "stability ai",
    "openai",
    "virtual artist",
    "virtual idol",
    "avatar",
    "remix",
    "cover",
    "soundtrack",
    "film score",
    "sync",
    "tiktok",
    "reels",
    "shorts",
    "viral",
    "challenge",
    "meme",
    "creator",
    "ugc",
    "streaming",
    "subscription",
    "royalty",
    "rights",
    "licensing",
    "copyright",
    "distribution",
    "spotify",
    "youtube",
    "soundcloud",
    "bandlab",
    "distrokid",
    "tunecore",
]


VANSO_RELEVANCE_KEYWORDS = [
    "mood",
    "ambient",
    "playlist",
    "short-form",
    "short audio",
    "music app",
    "streaming",
    "discovery",
    "distribution",
    "creator",
    "independent artist",
    "fan",
    "fandom",
]


VIZASOUND_RELEVANCE_KEYWORDS = [
    "ai song",
    "song generator",
    "music generator",
    "ai music video",
    "music video",
    "video generator",
    "virtual performer",
    "contest",
    "competition",
    "award",
    "live stream",
    "youtube premiere",
    "episode",
]


LOW_VALUE_KEYWORDS = [
    "restaurant",
    "bill",
    "airport",
    "crime",
    "lawsuit against",
    "divorce",
    "dating",
    "red carpet",
    "box office",
    "soccer transfer",
    "stock market",
    "wordle",
    "crossword",
]


SOCIAL_FUN_KEYWORDS = [
    "viral",
    "meme",
    "reaction",
    "debate",
    "discourse",
    "fan edit",
    "fandom",
    "stan",
    "parody",
    "joke",
    "easter egg",
    "trend",
    "challenge",
    "remix",
]


CULTURE_FUN_KEYWORDS = [
    "film",
    "movie",
    "cinema",
    "tv",
    "series",
    "streaming series",
    "trailer",
    "teaser",
    "adaptation",
    "prequel",
    "sequel",
    "remake",
    "reboot",
    "horror",
    "sci-fi",
    "fantasy",
    "animation",
    "anime",
    "director",
    "filmmaker",
    "actor",
    "actress",
    "cast",
    "screenwriter",
    "producer",
    "auteur",
    "franchise",
    "video game adaptation",
    "letterboxd",
    "festival",
    "cannes",
    "sundance",
    "venice",
    "berlin",
    "toronto",
    "tribeca",
    "sxsw",
    "locarno",
    "art",
    "artist",
    "gallery",
    "museum",
    "exhibition",
    "installation",
    "contemporary art",
    "documentary",
    "youth culture",
    "fashion",
    "visual",
    "soundtrack",
    "score",
    "composer",
]


CONTENT_NOISE_MARKERS = [
    "skip to main content",
    "jump to content",
    "open navigation menu",
    "newsletter",
    "search search",
    "menu menu",
    "javascript",
    "your browser appears to have javascript disabled",
    "access to this page has been denied",
    "$refs.firstmenuitem.focus",
    "crossword",
    "wordle",
    "sign up",
    "open menu",
]


HOLIDAY_VALUE_KEYWORDS = [
    # 原有节日
    "father",
    "mother",
    "valentine",
    "halloween",
    "christmas",
    "new year",
    "thanksgiving",
    "easter",
    "dragon boat",
    "mid-autumn",
    "labor",
    "youth",
    "music",
    "carnival",
    "eid",
    "ramadan",
    "diwali",
    # 新增：各类解放日/独立日/民族节日
    "independence",
    "liberation",
    "national",
    "republic",
    "revolution",
    "freedom",
    "unity",
    "solidarity",
    "remembrance",
    "memorial",
    "victory",
    "armistice",
    "reconciliation",
    # 新增：宗教与文化节日
    "holi",
    "dussehra",
    "pongal",
    "vesak",
    "buddha",
    "eid al",
    "muharram",
    "mawlid",
    "rosh hashana",
    "yom kippur",
    "hanukkah",
    "passover",
    "pentecost",
    "ascension",
    "corpus christi",
    "assumption",
    "all saints",
    "all souls",
    "epiphany",
    "orthodox",
    "lantern",
    "songkran",
    "thaipusam",
    "wesak",
    "loy krathong",
    "nyepi",
    "galungan",
    "waisak",
    "onam",
    "pongal",
    "vijayadashami",
    "navaratri",
    # 新增：体育/文化大事
    "world cup",
    "olympic",
    "carnival",
    "mardi gras",
    "oktoberfest",
    "bonfire",
    "pride",
    "heritage",
    "culture",
    "arts",
    "spring",
    "harvest",
    "autumn",
    "summer",
    "winter",
    "festival",
    "bank holiday",
    "public holiday",
    "day off",
    "holiday",
]


@dataclass(frozen=True)
class FeedSource:
    key: str
    name: str
    url: str
    section: str
    max_age_days: int
    max_items: int
    priority: int
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


@dataclass
class NewsItem:
    source_key: str
    source_name: str
    section: str
    title: str
    link: str
    summary: str
    published_at: datetime | None
    priority: int
    tag: str
    score: float
    business_score: float = 0.0
    score_reasons: list[str] | None = None
    cn_summary: str = ""
    article_excerpt: str = ""
    cn_title: str = ""
    why_it_matters: str = ""
    market_hint: str = ""
    action_hint: str = ""
    risk_note: str = ""


FEED_SOURCES = [
    FeedSource(
        key="sony",
        name="Sony Music",
        url="https://www.sonymusic.com/feed/",
        section="head_releases",
        max_age_days=2,
        max_items=3,
        priority=100,
        include_keywords=tuple(HEAD_RELEASE_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="warner",
        name="Warner Music Group",
        url="https://www.wmg.com/news/category/press-release/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=3,
        priority=95,
        include_keywords=tuple(HEAD_RELEASE_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="universal",
        name="Universal Music Group",
        url="https://www.universalmusic.com/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=3,
        priority=95,
        include_keywords=tuple(HEAD_RELEASE_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="billboard",
        name="Billboard",
        url="https://www.billboard.com/feed/",
        section="music_news",
        max_age_days=2,
        max_items=4,
        priority=90,
    ),
    FeedSource(
        key="billboard_head_release",
        name="Billboard",
        url="https://www.billboard.com/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=4,
        priority=84,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="rolling_stone",
        name="Rolling Stone",
        url="https://www.rollingstone.com/music/music-news/feed/",
        section="music_news",
        max_age_days=2,
        max_items=3,
        priority=88,
    ),
    FeedSource(
        key="rolling_stone_head_release",
        name="Rolling Stone",
        url="https://www.rollingstone.com/music/music-news/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=3,
        priority=82,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="pitchfork",
        name="Pitchfork",
        url="https://pitchfork.com/feed/feed-news/rss",
        section="music_news",
        max_age_days=2,
        max_items=3,
        priority=85,
    ),
    FeedSource(
        key="pitchfork_head_release",
        name="Pitchfork",
        url="https://pitchfork.com/feed/feed-news/rss",
        section="head_releases",
        max_age_days=3,
        max_items=3,
        priority=80,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="nme_music_head_release",
        name="NME Music",
        url="https://www.nme.com/news/music/feed",
        section="head_releases",
        max_age_days=3,
        max_items=4,
        priority=78,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="stereogum_head_release",
        name="Stereogum",
        url="https://www.stereogum.com/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=4,
        priority=76,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="consequence_music_head_release",
        name="Consequence Music",
        url="https://consequence.net/category/music/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=4,
        priority=74,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="brooklynvegan_head_release",
        name="BrooklynVegan",
        url="https://www.brooklynvegan.com/category/music/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=4,
        priority=72,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="freshhiphoprnb_head_release",
        name="FreshHipHopR&B",
        url="https://freshhiphoprnb.com/feed/",
        section="head_releases",
        max_age_days=3,
        max_items=4,
        priority=70,
        include_keywords=tuple(HEAD_RELEASE_MEDIA_INCLUDE),
        exclude_keywords=tuple(HEAD_RELEASE_EXCLUDE),
    ),
    FeedSource(
        key="mbw",
        name="Music Business Worldwide",
        url="https://www.musicbusinessworldwide.com/feed/",
        section="music_ai_industry",
        max_age_days=3,
        max_items=4,
        priority=90,
        include_keywords=tuple(AI_INDUSTRY_KEYWORDS),
    ),
    FeedSource(
        key="techcrunch_ai",
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        section="music_ai_industry",
        max_age_days=3,
        max_items=3,
        priority=80,
    ),
    FeedSource(
        key="verge_ai",
        name="The Verge AI",
        url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        section="music_ai_industry",
        max_age_days=3,
        max_items=3,
        priority=80,
    ),
    FeedSource(
        key="daily_dot",
        name="Daily Dot",
        url="https://dailydot.com/unclick/feed",
        section="social_trends",
        max_age_days=3,
        max_items=3,
        priority=80,
        include_keywords=tuple(SOCIAL_KEYWORDS),
    ),
    FeedSource(
        key="variety_film",
        name="Variety Film",
        url="https://variety.com/v/film/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=3,
        priority=75,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="deadline_film",
        name="Deadline Film",
        url="https://deadline.com/v/film/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=4,
        priority=78,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="deadline_tv",
        name="Deadline TV",
        url="https://deadline.com/v/tv/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=3,
        priority=74,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="thr_movies",
        name="The Hollywood Reporter Movies",
        url="https://www.hollywoodreporter.com/c/movies/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=4,
        priority=76,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="thr_tv",
        name="The Hollywood Reporter TV",
        url="https://www.hollywoodreporter.com/c/tv/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=3,
        priority=72,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="indiewire_film",
        name="IndieWire Film",
        url="https://www.indiewire.com/c/film/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=4,
        priority=74,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="guardian_film",
        name="The Guardian Film",
        url="https://www.theguardian.com/film/rss",
        section="culture_art",
        max_age_days=3,
        max_items=3,
        priority=70,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="nme_film",
        name="NME Film",
        url="https://www.nme.com/film/feed",
        section="culture_art",
        max_age_days=3,
        max_items=3,
        priority=68,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="hyperallergic",
        name="Hyperallergic",
        url="https://hyperallergic.com/feed/",
        section="culture_art",
        max_age_days=3,
        max_items=3,
        priority=66,
        include_keywords=tuple(CULTURE_KEYWORDS),
    ),
    FeedSource(
        key="the_hill",
        name="The Hill",
        url="https://thehill.com/feed/?feed=partnerfeed-news-feed&format=rss",
        section="politics",
        max_age_days=2,
        max_items=3,
        priority=82,
        include_keywords=tuple(POLITICS_KEYWORDS),
    ),
    FeedSource(
        key="npr_politics",
        name="NPR Politics",
        url="https://feeds.npr.org/1001/rss.xml",
        section="politics",
        max_age_days=2,
        max_items=3,
        priority=80,
        include_keywords=tuple(POLITICS_KEYWORDS),
    ),
    FeedSource(
        key="reuters_world",
        name="Reuters World",
        url="https://feeds.reuters.com/reuters/worldNews",
        section="politics",
        max_age_days=2,
        max_items=4,
        priority=90,
        include_keywords=tuple(POLITICS_KEYWORDS),
    ),
    FeedSource(
        key="ap_politics",
        name="AP News",
        url="https://feeds.apnews.com/rss/apf-politics",
        section="politics",
        max_age_days=2,
        max_items=3,
        priority=88,
        include_keywords=tuple(POLITICS_KEYWORDS),
    ),
    FeedSource(
        key="bbc_world",
        name="BBC World",
        url="https://feeds.bbci.co.uk/news/world/rss.xml",
        section="politics",
        max_age_days=2,
        max_items=4,
        priority=87,
        include_keywords=tuple(POLITICS_KEYWORDS),
    ),
    FeedSource(
        key="guardian_world",
        name="The Guardian World",
        url="https://www.theguardian.com/world/rss",
        section="politics",
        max_age_days=2,
        max_items=3,
        priority=82,
        include_keywords=tuple(POLITICS_KEYWORDS),
    ),
    # ── 社媒热点新信源 ──────────────────────────────────────
    FeedSource(
        key="buzzfeed_news",
        name="BuzzFeed News",
        url="https://www.buzzfeed.com/celeb.xml",
        section="social_trends",
        max_age_days=2,
        max_items=3,
        priority=78,
        include_keywords=tuple(SOCIAL_KEYWORDS),
    ),
    FeedSource(
        key="mashable_social",
        name="Mashable",
        url="https://mashable.com/feeds/rss/all",
        section="social_trends",
        max_age_days=2,
        max_items=3,
        priority=76,
        include_keywords=tuple(SOCIAL_KEYWORDS),
    ),
    FeedSource(
        key="variety_digital",
        name="Variety Digital",
        url="https://variety.com/v/digital/feed/",
        section="social_trends",
        max_age_days=2,
        max_items=3,
        priority=74,
        include_keywords=tuple(SOCIAL_KEYWORDS),
    ),
    FeedSource(
        key="reddit_popular",
        name="Reddit r/popular",
        url="https://www.reddit.com/r/popular/.rss",
        section="social_trends",
        max_age_days=1,
        max_items=4,
        priority=72,
        include_keywords=tuple(SOCIAL_KEYWORDS),
    ),
    FeedSource(
        key="knowyourmeme",
        name="Know Your Meme",
        url="https://knowyourmeme.com/memes/all.rss",
        section="social_trends",
        max_age_days=2,
        max_items=3,
        priority=80,
    ),
    FeedSource(
        key="tmz",
        name="TMZ",
        url="https://www.tmz.com/rss.xml",
        section="social_trends",
        max_age_days=1,
        max_items=3,
        priority=70,
        include_keywords=tuple(SOCIAL_KEYWORDS),
    ),
]


PRICE_TRACKERS = [
    {
        "key": "spotify_us",
        "name": "Spotify Premium (US)",
        "url": "https://www.spotify.com/us/premium/",
        "source_url": "https://www.spotify.com/us/premium/",
        "plans": ["Individual", "Student", "Duo", "Family"],
    },
    {
        "key": "apple_music_us",
        "name": "Apple Music (US)",
        "url": "https://www.apple.com/apple-music/",
        "source_url": "https://www.apple.com/apple-music/",
        "plans": ["Individual", "Student", "Family", "Voice"],
    },
    {
        "key": "amazon_music_us",
        "name": "Amazon Music Unlimited (US)",
        "url": "https://www.amazon.com/music/unlimited",
        "source_url": "https://www.amazon.com/music/unlimited",
        "plans": ["Individual", "Student", "Family", "Prime"],
    },
]


HOLIDAY_COUNTRIES = [
    # 仅关注以下 10 个国家的节庆预警
    "GB", "ES", "FR", "DE", "IT",       # 英西法德意
    "MX", "PH", "MY", "PT", "BR",       # 墨西哥、菲律宾、马来西亚、葡萄牙、巴西
]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    ensure_data_dir()
    if not STATE_PATH.exists():
        return {
            "price_snapshots": {},
            "translation_cache": {},
            "article_cache": {},
            "llm_cache": {},
            "delivery": {},
        }
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state.setdefault("price_snapshots", {})
        state.setdefault("translation_cache", {})
        state.setdefault("article_cache", {})
        state.setdefault("llm_cache", {})
        state.setdefault("delivery", {})
        return state
    except (json.JSONDecodeError, OSError):
        return {
            "price_snapshots": {},
            "translation_cache": {},
            "article_cache": {},
            "llm_cache": {},
            "delivery": {},
        }


def save_state(state: dict[str, Any]) -> None:
    ensure_data_dir()
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def decode_web_text(raw: bytes, declared_charset: str | None = None) -> str:
    candidates: list[str] = []
    if declared_charset:
        candidates.append(declared_charset)
    candidates.extend(["utf-8", "utf-8-sig", "cp1252", "latin-1"])

    seen: set[str] = set()
    ranked: list[tuple[tuple[int, int, int], str]] = []
    for encoding in candidates:
        normalized = encoding.lower().strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            text = raw.decode(normalized, errors="replace")
        except LookupError:
            continue
        mojibake_penalty = sum(text.count(marker) for marker in ("鈥", "锟", "Ã", "â", "Â"))
        replacement_penalty = text.count("\ufffd")
        cjk_bonus = -len(re.findall(r"[\u4e00-\u9fff]", text))
        ranked.append(((mojibake_penalty, replacement_penalty, cjk_bonus), text))

    if not ranked:
        return raw.decode("utf-8", errors="replace")
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def fetch_text(url: str, timeout: int = 8) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml,text/xml,application/rss+xml,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read()
            return decode_web_text(raw, charset)
    except urllib.error.URLError:
        result = subprocess.run(
            [
                "curl",
                "-L",
                "-sS",
                "--compressed",
                "--connect-timeout",
                str(min(timeout, 4)),
                "--max-time",
                str(timeout),
                url,
            ],
            capture_output=True,
            timeout=timeout,
            check=True,
        )
        return decode_web_text(result.stdout, "utf-8")


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int = 20,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = headers or {}
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset, errors="replace"))
    except urllib.error.URLError:
        cmd = [
            "curl",
            "-sS",
            "--compressed",
            "--connect-timeout",
            str(min(timeout, 4)),
            "--max-time",
            str(timeout),
            "-X",
            "POST",
        ]
        cmd.extend(["-H", "Content-Type: application/json; charset=utf-8"])
        for header_key, header_value in headers.items():
            cmd.extend(["-H", f"{header_key}: {header_value}"])
        cmd.extend(["-d", json.dumps(payload, ensure_ascii=False), url])
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
        return json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")


def truncate_text(text: str, max_len: int) -> str:
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def normalize_title_key(text: str) -> str:
    normalized = normalize_whitespace(text).lower()
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    normalized = re.sub(r"\[[^\]]*\]", " ", normalized)
    normalized = re.sub(r"\s*[-|:]\s*(billboard|rolling stone|pitchfork|variety|spotify|tiktok|youtube).*$", "", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized)
    return normalize_whitespace(normalized)


def is_item_in_report_window(item_dt: datetime | None, report_dt: datetime) -> bool:
    if item_dt is None:
        return False
    local_dt = item_dt.astimezone(report_dt.tzinfo)
    previous_date = report_dt.date() - timedelta(days=1)
    if local_dt.date() == previous_date:
        return True
    return local_dt.date() == report_dt.date() and local_dt <= report_dt


def llm_is_configured() -> bool:
    return bool(OPENAI_API_KEY and OPENAI_BASE_URL and OPENAI_MODEL)


def openai_chat_url() -> str:
    base_url = OPENAI_BASE_URL.strip()
    if not base_url:
        return ""
    if not re.match(r"^https?://", base_url, flags=re.I):
        base_url = "https://" + base_url
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return base_url + "/chat/completions"
    return base_url + "/v1/chat/completions"


def extract_json_payload(raw_text: str) -> dict[str, Any]:
    cleaned = normalize_whitespace(raw_text)
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"(\{.*\})", raw_text, flags=re.S)
    if not match:
        raise ValueError("LLM response missing JSON object")
    parsed = json.loads(match.group(1))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON is not an object")
    return parsed


def fetch_json(url: str, timeout: int = 12) -> Any:
    return json.loads(fetch_text(url, timeout=timeout))


def post_form_json(
    url: str,
    form_fields: list[tuple[str, str]],
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> Any:
    headers = headers or {}
    encoded = urllib.parse.urlencode(form_fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset, errors="replace"))
    except urllib.error.URLError:
        cmd = [
            "curl",
            "-sS",
            "--compressed",
            "--connect-timeout",
            str(min(timeout, 4)),
            "--max-time",
            str(timeout),
            "-X",
            "POST",
        ]
        for header_key, header_value in headers.items():
            cmd.extend(["-H", f"{header_key}: {header_value}"])
        for key, value in form_fields:
            cmd.extend(["--data-urlencode", f"{key}={value}"])
        cmd.append(url)
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
        return json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")


def clean_html(raw: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def keyword_matches(text: str, keyword: str) -> bool:
    normalized = normalize_whitespace(text).lower()
    normalized_keyword = normalize_whitespace(keyword).lower()
    if re.fullmatch(r"[a-z0-9\s/+-]+", normalized_keyword):
        pattern = r"\b" + re.escape(normalized_keyword).replace(r"\ ", r"\s+") + r"\b"
        return re.search(pattern, normalized) is not None
    return normalized_keyword in normalized


def parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for parser in (
        lambda value: parsedate_to_datetime(value),
        lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    ):
        try:
            parsed = parser(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError, IndexError):
            continue
    return None


def parse_feed_items(feed_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(feed_text)
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    items: list[dict[str, Any]] = []
    channel = root.find(f"{namespace}channel")
    if channel is not None:
        xml_items = channel.findall(f"{namespace}item")
        for item in xml_items:
            title = item.findtext(f"{namespace}title") or ""
            link = item.findtext(f"{namespace}link") or ""
            description = item.findtext(f"{namespace}description") or ""
            encoded = ""
            for child in item:
                if child.tag.endswith("encoded") and child.text:
                    encoded = child.text
                    break
            pub_date = item.findtext(f"{namespace}pubDate")
            items.append(
                {
                    "title": normalize_whitespace(clean_html(title)),
                    "link": normalize_whitespace(link),
                    "summary": normalize_whitespace(clean_html(encoded or description)),
                    "published_at": parse_datetime(pub_date),
                }
            )
        return items

    for entry in root.findall(f".//{namespace}entry"):
        title = entry.findtext(f"{namespace}title") or ""
        link = ""
        for link_node in entry.findall(f"{namespace}link"):
            candidate = link_node.attrib.get("href", "")
            if candidate:
                link = candidate
                break
        summary = entry.findtext(f"{namespace}summary") or entry.findtext(
            f"{namespace}content"
        ) or ""
        published = entry.findtext(f"{namespace}published") or entry.findtext(
            f"{namespace}updated"
        )
        items.append(
            {
                "title": normalize_whitespace(clean_html(title)),
                "link": normalize_whitespace(link),
                "summary": normalize_whitespace(clean_html(summary)),
                "published_at": parse_datetime(published),
            }
        )
    return items


def first_sentence(text: str, max_len: int = 240) -> str:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return ""
    match = re.split(r"(?<=[\.\!\?。！？])\s+", cleaned, maxsplit=1)
    sentence = match[0]
    if len(sentence) <= max_len:
        return sentence
    return sentence[: max_len - 1].rstrip() + "…"


def is_noisy_content(text: str) -> bool:
    lowered = normalize_whitespace(text).lower()
    if not lowered:
        return False
    if contains_any(lowered, CONTENT_NOISE_MARKERS):
        return True
    if lowered.count("menu") >= 2 or lowered.count("search") >= 2:
        return True
    return False


def strip_source_trail(text: str, source_name: str) -> str:
    """清除摘要末尾的信源名残留，如 '- Music Business Worldwide Music Business ...'"""
    if not source_name:
        return text
    # 匹配 " - SourceName" 或 " — SourceName" 及其后重复的信源名
    pattern = r"\s*[-—]\s*" + re.escape(source_name) + r"\s*(?:" + re.escape(source_name) + r"\s*)*(?:\S*\s*){0,5}$"
    cleaned = re.sub(pattern, "", text, flags=re.I).strip()
    # 如果没匹配到完整模式，尝试简单清除 " - SourceName" 尾部
    if cleaned == text and source_name in text:
        simple = re.sub(r"\s*[-—]\s*" + re.escape(source_name) + r".*$", "", text, flags=re.I).strip()
        if simple and len(simple) > len(text) * 0.3:
            cleaned = simple
    return cleaned if cleaned else text


def summary_source_text(item: NewsItem) -> str:
    if item.article_excerpt:
        excerpt = first_sentence(item.article_excerpt, max_len=360)
        if excerpt and not is_noisy_content(excerpt):
            return strip_source_trail(excerpt, item.source_name)
    if item.summary:
        summary = first_sentence(item.summary, max_len=280)
        if summary and not is_noisy_content(summary):
            return strip_source_trail(summary, item.source_name)
    return item.title


def title_source_text(item: NewsItem) -> str:
    return item.title


def clean_title_for_summary(title: str) -> str:
    return normalize_whitespace(
        title.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    )


def title_based_cn_summary(item: NewsItem) -> str:
    title = clean_title_for_summary(item.title)
    patterns: list[tuple[re.Pattern[str], Any]] = [
        (
            re.compile(r"(?i)^(.+?) hit[s]? the ['\"]?(.+?)['\"]? in new song for ['\"]?(.+?)['\"]?$"),
            lambda m: f"{m.group(1)} 以新歌《{m.group(2)}》为《{m.group(3)}》带来联动曝光。",
        ),
        (
            re.compile(r"(?i)^(.+?) and (.+?) preview new song ['\"]?(.+?)['\"]? in (.+)$"),
            lambda m: f"{m.group(1)} 与 {m.group(2)} 预告合作新歌《{m.group(3)}》，并借 {m.group(4)} 释出预热片段。",
        ),
        (
            re.compile(r"(?i)^(.+?) announce(?:s)? new album ['\"]?(.+?)['\"]?$"),
            lambda m: f"{m.group(1)} 宣布推出新专辑《{m.group(2)}》。",
        ),
        (
            re.compile(r"(?i)^(.+?) announce(?:s)? (?:their |a )?new album (.+)$"),
            lambda m: f"{m.group(1)} 宣布新专辑《{m.group(2)}》的相关动态。",
        ),
        (
            re.compile(r"(?i)^(.+?) addresses? no-show at (.+)$"),
            lambda m: f"{m.group(1)} 回应在 {m.group(2)} 的缺席争议。",
        ),
        (
            re.compile(r"(?i)^(.+?) shot [& ]+hospitalized in (.+)$"),
            lambda m: f"{m.group(1)} 在 {m.group(2)} 发生中枪并住院事件。",
        ),
        (
            re.compile(r"(?i)^(.+?) .*cancel.* concert.*$"),
            lambda m: f"{m.group(1)} 取消了原定演出。",
        ),
        (
            re.compile(r"(?i)^(.+?) defends? (.+) booking.*$"),
            lambda m: f"{m.group(1)} 就 {m.group(2)} 的演出安排作出辩护。",
        ),
        (
            re.compile(r"(?i)^(.+?) sign(?:s|ed)? (.+)$"),
            lambda m: f"{m.group(1)} 公布新的签约或合作动态：{m.group(2)}。",
        ),
        (
            re.compile(r"(?i)^(.+?) extends? global partnership with (.+)$"),
            lambda m: f"{m.group(1)} 与 {m.group(2)} 延续全球合作关系。",
        ),
        (
            re.compile(r"(?i)^(.+?) exits? YouTube after (.+)$"),
            lambda m: f"{m.group(1)} 在 YouTube 任职 {m.group(2)} 后离开平台。",
        ),
        (
            re.compile(r"(?i)^A folk musician had her voice cloned by AI.*$"),
            lambda m: "一位民谣音乐人的声音被 AI 克隆，其录音作品还被版权方错误认领。",
        ),
        (
            re.compile(r"(?i)^Gemini is making it faster for (.+)$"),
            lambda m: f"Gemini 正让 {m.group(1)} 的触达速度变得更快。",
        ),
        (
            re.compile(r"(?i)^AI startup Rocket offers (.+)$"),
            lambda m: f"AI 初创公司 Rocket 推出 {m.group(1)} 的服务方案。",
        ),
        (
            re.compile(r"(?i)^(.+?) reveals? (.+ lineup.*)$"),
            lambda m: f"{m.group(1)} 公布了 {m.group(2)}。",
        ),
        (
            re.compile(r"(?i)^5 takeaways from (.+)$"),
            lambda m: f"这条新闻总结了 {m.group(1)} 的 5 个关键信息点。",
        ),
        (
            re.compile(r"(?i)^Trump suggests US could charge toll for (.+)$"),
            lambda m: f"特朗普表示，美国可能会就 {m.group(1)} 收取通行费用。",
        ),
        (
            re.compile(r"(?i)^As Trump's deadline approaches, Iranian leaders respond in defiance$"),
            lambda m: "随着特朗普设定的最后期限临近，伊朗方面以强硬姿态作出回应。",
        ),
        (
            re.compile(r"(?i)^Beer cans, helium balloons and mortgages: (.+)$"),
            lambda m: f"这条新闻梳理了战争对啤酒罐、氦气气球和房贷等领域带来的 {m.group(1)}。",
        ),
        (
            re.compile(r"(?i)^listen to (.+?) new song ['\"]?(.+?)['\"]?$"),
            lambda m: f"收听 {m.group(1)} 的新歌《{m.group(2)}》。",
        ),
        (
            re.compile(r"(?i)^(.+?) get[s]? .+ on new song ['\"]?(.+?)['\"]?$"),
            lambda m: f"{m.group(1)} 发布新歌《{m.group(2)}》。",
        ),
        (
            re.compile(r"(?i)^new music releases and upcoming albums in (\d{4})$"),
            lambda m: f"{m.group(1)} 年最新音乐发行与即将推出的专辑汇总。",
        ),
    ]

    for pattern, formatter in patterns:
        match = pattern.match(title)
        if match:
            return formatter(match)

    return trim_title(title, 90)


def heuristic_cn_summary(item: NewsItem) -> str:
    return title_based_cn_summary(item)


def translate_via_deepl(text: str, timeout: int = 20) -> str:
    if not DEEPL_API_KEY:
        raise RuntimeError("DEEPL_API_KEY is not configured")
    payload = post_form_json(
        DEEPL_API_URL,
        form_fields=[
            ("text", text),
            ("target_lang", "ZH"),
            ("source_lang", "EN"),
            ("preserve_formatting", "1"),
        ],
        headers={"Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}"},
        timeout=timeout,
    )
    translations = payload.get("translations", [])
    if not translations:
        raise ValueError("DeepL response missing translations")
    translated = normalize_whitespace(translations[0].get("text", ""))
    if not translated:
        raise ValueError("DeepL returned empty translation")
    return translated


def translate_via_google_unofficial(text: str, timeout: int = 12) -> str:
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl=zh-CN&dt=t&q={urllib.parse.quote(text)}"
    )
    payload = fetch_json(url, timeout=timeout)
    translated = "".join(
        part[0] for part in payload[0] if isinstance(part, list) and part and part[0]
    )
    translated = normalize_whitespace(translated)
    if not translated:
        raise ValueError("Google unofficial translate returned empty translation")
    return translated


def translate_text_to_zh(
    text: str,
    state: dict[str, Any],
    diagnostics: list[str],
    cache_namespace: str = "default",
    record_errors: bool = False,
) -> str:
    text = normalize_whitespace(text)
    if not text:
        return ""
    cache = state.setdefault("translation_cache", {})
    cache_key = hashlib.sha256(f"{cache_namespace}|{text}".encode("utf-8")).hexdigest()
    with TRANSLATION_CACHE_LOCK:
        if cache_key in cache:
            return cache[cache_key]

    if not REMOTE_TRANSLATION_ENABLED:
        with TRANSLATION_CACHE_LOCK:
            cache[cache_key] = text
        return text

    try:
        if DEEPL_API_KEY:
            translated = translate_via_deepl(text, timeout=20)
        else:
            translated = translate_via_google_unofficial(text, timeout=12)
        with TRANSLATION_CACHE_LOCK:
            cache[cache_key] = translated
        return translated
    except (
        urllib.error.URLError,
        http.client.RemoteDisconnected,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
        TypeError,
        IndexError,
    ) as exc:
        if record_errors:
            diagnostics.append(f"翻译失败: {exc}")

    with TRANSLATION_CACHE_LOCK:
        cache[cache_key] = text
    return text


def enrich_cn_summaries(
    sections: dict[str, list[NewsItem]],
    state: dict[str, Any],
    diagnostics: list[str],
) -> None:
    items: list[NewsItem] = []
    for section_items in sections.values():
        items.extend(section_items)

    def translate_item(item: NewsItem) -> tuple[NewsItem, str, str, bool]:
        if ENGLISH_OUTPUT_MODE:
            return item, item.title, item.title, False
        summary_text = summary_source_text(item)
        # 如果摘要来源就是标题本身，标记为"无独立摘要"
        summary_is_just_title = (summary_text == item.title)
        translated_summary = translate_text_to_zh(
            summary_text,
            state=state,
            diagnostics=diagnostics,
            cache_namespace=f"{item.section}:summary",
            record_errors=False,
        )
        if translated_summary == summary_text and not has_cjk(summary_text):
            translated_summary = heuristic_cn_summary(item)

        title_text = title_source_text(item)
        translated_title = translate_text_to_zh(
            title_text,
            state=state,
            diagnostics=diagnostics,
            cache_namespace=f"{item.section}:title",
            record_errors=False,
        )
        if translated_title == title_text and not has_cjk(title_text):
            translated_title = heuristic_cn_summary(item)
        return item, translated_summary, translated_title, summary_is_just_title

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(translate_item, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            try:
                item, translated_summary, translated_title, summary_is_just_title = future.result()
            except Exception as exc:
                diagnostics.append(f"翻译线程失败，已回退: {exc}")
                continue
            # 如果摘要来源就是标题，cn_summary 置空（避免摘要=标题的重复）
            if summary_is_just_title:
                item.cn_summary = ""
            else:
                item.cn_summary = trim_title(
                    translated_summary if has_cjk(translated_summary) else "",
                    120,
                )
            if not item.cn_title:
                item.cn_title = trim_title(
                    translated_title if has_cjk(translated_title) else heuristic_cn_summary(item),
                    64,
                )


def fetch_article_excerpt(url: str, state: dict[str, Any], diagnostics: list[str]) -> str:
    cache = state.setdefault("article_cache", {})
    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    with TRANSLATION_CACHE_LOCK:
        if cache_key in cache:
            return cache[cache_key]

    try:
        raw_html = fetch_text(url, timeout=12)
        excerpt = truncate_text(clean_html(raw_html), ARTICLE_EXCERPT_LIMIT)
    except (
        urllib.error.URLError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TimeoutError,
    ) as exc:
        diagnostics.append(f"正文抓取失败: {url} ({exc})")
        excerpt = ""

    with TRANSLATION_CACHE_LOCK:
        cache[cache_key] = excerpt
    return excerpt


def enrich_article_excerpts(
    sections: dict[str, list[NewsItem]],
    state: dict[str, Any],
    diagnostics: list[str],
) -> None:
    items: list[NewsItem] = []
    for section_items in sections.values():
        items.extend(section_items)

    def load_excerpt(item: NewsItem) -> tuple[NewsItem, str]:
        if not item.link:
            return item, ""
        return item, fetch_article_excerpt(item.link, state, diagnostics)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(load_excerpt, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            item, excerpt = future.result()
            item.article_excerpt = excerpt


def call_llm_json(
    system_prompt: str,
    user_payload: dict[str, Any],
    state: dict[str, Any],
    diagnostics: list[str],
    cache_namespace: str,
) -> dict[str, Any] | None:
    if not llm_is_configured():
        return None

    serialized_payload = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)
    cache = state.setdefault("llm_cache", {})
    cache_basis = {
        "namespace": cache_namespace,
        "model": OPENAI_MODEL,
        "system_prompt": system_prompt,
        "payload": user_payload,
    }
    cache_key = hashlib.sha256(
        json.dumps(cache_basis, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    with TRANSLATION_CACHE_LOCK:
        if cache_key in cache:
            return cache[cache_key]

    request_payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": serialized_payload},
        ],
    }
    try:
        response = post_json(
            openai_chat_url(),
            request_payload,
            timeout=OPENAI_TIMEOUT,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        )
        choices = response.get("choices", [])
        if not choices:
            raise ValueError("LLM response missing choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        parsed = extract_json_payload(content)
    except (
        urllib.error.URLError,
        http.client.RemoteDisconnected,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        diagnostics.append(f"LLM 增强失败({cache_namespace}): {exc}")
        return None

    with TRANSLATION_CACHE_LOCK:
        cache[cache_key] = parsed
    return parsed


def enrich_items_with_llm(
    sections: dict[str, list[NewsItem]],
    state: dict[str, Any],
    diagnostics: list[str],
) -> None:
    items: list[NewsItem] = []
    for section_items in sections.values():
        items.extend(section_items)
    if not items:
        return

    enrich_article_excerpts(sections, state, diagnostics)
    enrich_cn_summaries(sections, state, diagnostics)
    if not llm_is_configured():
        return

    payload_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        payload_items.append(
            {
                "id": f"item_{index}",
                "section": SECTION_TITLES.get(item.section, item.section),
                "tag": item.tag,
                "source": item.source_name,
                "title": item.title,
                "summary": item.summary,
                "article_excerpt": truncate_text(item.article_excerpt, 900),
                "published_at": item.published_at.isoformat() if item.published_at else "",
                "link": item.link,
            }
        )

    system_prompt = (
        "你是海外音乐与内容运营分析师。"
        "请把输入新闻加工成适合中国团队阅读的运营情报，输出简体中文 JSON。"
        "每条新闻只给出更完整的中文标题和 60 到 110 字的一行摘要。"
        "摘要必须补充标题未涵盖的关键信息（时间、数据、平台、作品、影响点），不能重复或复述标题内容。"
        "不要写运营意义、可执行动作或模板化建议。"
        "不要杜撰未给出的事实，不确定就保守概括。"
    )
    payload = {
        "goal": "生成下午播报所需的中文情报条目",
        "items": payload_items,
        "output_schema": {
            "items": [
                {
                    "id": "item_1",
                    "cn_title": "中文标题",
                    "summary_zh": "60-110字一行摘要",
                }
            ]
        },
    }
    result = call_llm_json(system_prompt, payload, state, diagnostics, "item_enrichment")
    if not result:
        return

    result_items = result.get("items", [])
    if not isinstance(result_items, list):
        diagnostics.append("LLM 条目增强返回格式异常")
        return

    by_id = {payload_item["id"]: item for payload_item, item in zip(payload_items, items)}
    for enriched in result_items:
        if not isinstance(enriched, dict):
            continue
        item = by_id.get(enriched.get("id", ""))
        if not item:
            continue
        item.cn_title = normalize_whitespace(enriched.get("cn_title", "")) or item.cn_title or item.title
        candidate_summary = normalize_whitespace(enriched.get("summary_zh", "")) or item.cn_summary
        # LLM 摘要与标题重复时置空，不回退到 heuristic_cn_summary
        if candidate_summary and item.cn_title and candidate_summary == item.cn_title:
            candidate_summary = ""
        item.cn_summary = candidate_summary if has_cjk(candidate_summary) else ""
        item.why_it_matters = normalize_whitespace(enriched.get("why_it_matters", ""))
        item.market_hint = normalize_whitespace(enriched.get("market_hint", ""))
        item.action_hint = normalize_whitespace(enriched.get("action_hint", ""))
        item.risk_note = normalize_whitespace(enriched.get("risk_note", ""))


def empty_report_sections() -> dict[str, list[NewsItem]]:
    return {section: [] for section in SECTION_TITLES if section not in {"holiday_events", "ops_suggestions"}}


def enforce_report_limits(sections: dict[str, list[NewsItem]]) -> dict[str, list[NewsItem]]:
    limited = empty_report_sections()
    for section, items in sections.items():
        section_limit = SECTION_LIMITS.get(section, 3)
        sorted_items = sorted(
            items,
            key=lambda item: (
                item.score,
                item.published_at.timestamp() if item.published_at else 0,
            ),
            reverse=True,
        )
        limited[section] = sorted_items[:section_limit]

    all_items: list[tuple[str, NewsItem]] = [
        (section, item)
        for section in REPORT_SECTION_ORDER
        if section not in {"holiday_events", "ops_suggestions"}
        for item in limited.get(section, [])
    ]
    if len(all_items) <= MAX_REPORT_ITEMS:
        return limited

    keep_ids = {
        id(item)
        for _, item in sorted(
            all_items,
            key=lambda pair: (
                pair[1].score,
                pair[1].published_at.timestamp() if pair[1].published_at else 0,
            ),
            reverse=True,
        )[:MAX_REPORT_ITEMS]
    }
    for section in limited:
        limited[section] = [item for item in limited[section] if id(item) in keep_ids]
    return limited


def editorial_select_sections(
    sections: dict[str, list[NewsItem]],
    state: dict[str, Any],
    diagnostics: list[str],
    audit: dict[str, Any] | None = None,
) -> dict[str, list[NewsItem]]:
    fallback = enforce_report_limits(sections)
    if not llm_is_configured():
        return fallback

    candidate_items: list[NewsItem] = []
    for section in REPORT_SECTION_ORDER:
        if section in {"holiday_events", "ops_suggestions"}:
            continue
        candidate_items.extend(sections.get(section, []))
    if not candidate_items:
        return fallback

    payload_items: list[dict[str, Any]] = []
    id_to_item: dict[str, NewsItem] = {}
    for index, item in enumerate(candidate_items, start=1):
        item_id = f"item_{index}"
        id_to_item[item_id] = item
        payload_items.append(
            {
                "id": item_id,
                "section": item.section,
                "section_title": SECTION_TITLES.get(item.section, item.section),
                "source": item.source_name,
                "title": item.title,
                "summary": item.cn_summary if has_cjk(item.cn_summary) else heuristic_cn_summary(item),
                "score": round(item.score, 2),
                "business_score": round(item.business_score, 2),
                "score_reasons": item.score_reasons or [],
                "published_at": item.published_at.isoformat() if item.published_at else "",
                "link": item.link,
            }
        )

    system_prompt = (
        "你是 Vanso 与 Vizasound 的海外情报总编。"
        "Vanso 是 AI 音乐流媒体和短音频兴趣图谱平台；Vizasound 是 AI 音乐创作平台，承载 The Aidols 和 The Aimmys。"
        "请只做精选、合并和压缩，不要写运营意义/可执行动作这类模板废话。"
        "固定保留这些栏目：头部发行、AI·产业动向、社媒热点、文化·艺术界、国际政坛、节庆预警。"
        "头部发行：如有候选，尽量保留 3-6 条。"
        "AI·产业动向：如有候选，保留 3-6 条，关注 AI 音乐工具、流媒体平台、版权、创作者经济等方向。"
        "社媒热点：如有候选，保留 3-6 条。"
        "文化·艺术界：如有候选，保留 3-6 条。"
        "国际政坛：如有候选，保留 3-6 条重要政治新闻，不要求与业务强相关。"
        "普通生活争议、普通明星八卦不要选，除非具备社媒传播性、创作者经济、影音联动或可借势讨论价值。"
        "每条输出一行新闻稿口吻：标题要短，summary_zh 写关键信息、时间、数据或影响点。"
        "总条数最多 36 条；候选不足时栏目可以少选。输出 JSON。"
    )
    payload = {
        "items": payload_items,
        "section_limits": SECTION_LIMITS,
        "output_schema": {
            "items": [
                {
                    "id": "item_1",
                    "section": "head_releases",
                    "cn_title": "短标题",
                    "summary_zh": "一行摘要中标题后的内容，不超过 120 个中文字符",
                }
            ]
        },
    }
    result = call_llm_json(system_prompt, payload, state, diagnostics, "editorial_selection")
    if not result:
        return fallback

    selected = result.get("items", [])
    if not isinstance(selected, list):
        diagnostics.append("LLM 总编精选返回格式异常")
        return fallback

    refined = empty_report_sections()
    seen_links: set[str] = set()
    allowed_sections = {section for section in REPORT_SECTION_ORDER if section not in {"holiday_events", "ops_suggestions"}}
    for entry in selected:
        if not isinstance(entry, dict):
            continue
        item = id_to_item.get(str(entry.get("id", "")))
        if not item:
            continue
        section = str(entry.get("section") or item.section)
        if section not in allowed_sections:
            section = item.section
        if len(refined[section]) >= SECTION_LIMITS.get(section, 3):
            continue
        link_key = normalize_whitespace(item.link) or normalize_title_key(item.title)
        if link_key in seen_links:
            continue
        seen_links.add(link_key)
        item.section = section
        item.cn_title = trim_title(normalize_whitespace(str(entry.get("cn_title", ""))) or display_item_title(item), 70)
        summary_text = normalize_whitespace(str(entry.get("summary_zh", ""))) or item.cn_summary
        if not has_cjk(summary_text):
            summary_text = ""
        # 摘要与标题重复时置空
        if summary_text and item.cn_title and summary_text == item.cn_title:
            summary_text = ""
        item.cn_summary = trim_title(summary_text, 96)
        refined[section].append(item)

    for section, min_count in SECTION_MIN_COUNTS.items():
        fallback_items = fallback.get(section, [])
        if not fallback_items:
            continue
        target_count = min(min_count, SECTION_LIMITS.get(section, min_count), len(fallback_items))
        if len(refined.get(section, [])) >= target_count:
            continue
        existing_keys = {
            normalize_whitespace(item.link) or normalize_title_key(item.title)
            for item in refined.get(section, [])
        }
        for item in fallback_items:
            link_key = normalize_whitespace(item.link) or normalize_title_key(item.title)
            if link_key in existing_keys:
                continue
            refined[section].append(item)
            existing_keys.add(link_key)
            if len(refined[section]) >= target_count:
                break

    refined = enforce_report_limits(refined)
    selected_count = sum(len(items) for items in refined.values())
    if selected_count < min(4, len(candidate_items)):
        diagnostics.append("LLM 总编精选有效条目过少，已回退到规则复筛结果")
        return fallback

    if audit is not None:
        audit["llm_selected"] = [
            audit_news_item(item)
            for section in REPORT_SECTION_ORDER
            if section not in {"holiday_events", "ops_suggestions"}
            for item in refined.get(section, [])
        ]
    return refined


def translate_holiday_name(
    name: str,
    state: dict[str, Any],
    diagnostics: list[str],
) -> str:
    holiday_map = {
        "Early May Bank Holiday": "五月初银行假日",
        "Spring Bank Holiday": "春季银行假日",
        "Summer Bank Holiday": "夏季银行假日",
        "Truman Day": "杜鲁门日",
        "Victoire 1945": "1945 胜利纪念日",
        "Victory in Europe Day": "欧洲胜利日",
        "Fiesta de la Comunidad de Madrid": "马德里自治区日",
        "Independence Day": "独立日",
        "Christmas Day": "圣诞节",
        "Christmas Eve": "圣诞夜",
        "New Year's Day": "元旦",
        "New Year's Eve": "跨年夜",
        "Good Friday": "耶稣受难日",
        "Easter Monday": "复活节星期一",
        "Easter Sunday": "复活节",
        "Labour Day": "劳动节",
        "May Day": "五一节",
        "Thanksgiving": "感恩节",
        "Thanksgiving Day": "感恩节",
        "Valentine's Day": "情人节",
        "Halloween": "万圣节",
        "All Saints' Day": "万圣节",
        "All Souls' Day": "万灵节",
        "St. Patrick's Day": "圣帕特里克节",
        "Martin Luther King Jr. Day": "马丁·路德·金纪念日",
        "Presidents' Day": "总统日",
        "Memorial Day": "阵亡将士纪念日",
        "Veterans Day": "退伍军人节",
        "Columbus Day": "哥伦布日",
        "Juneteenth": "六月节",
        "Canada Day": "加拿大日",
        "Bastille Day": "法国国庆日",
        "German Unity Day": "德国统一日",
        "Day of German Unity": "德国统一日",
        "National Day": "国庆日",
        "Republic Day": "共和国日",
        " Liberation Day": "解放日",
        "Epiphany": "主显节",
        "Ascension Day": "耶稣升天节",
        "Whit Monday": "圣灵降临节星期一",
        "Corpus Christi": "基督圣体圣血节",
        "Assumption of Mary": "圣母升天节",
        "Immaculate Conception": "圣母无染原罪节",
        "Feast of the Immaculate Conception": "圣母无染原罪节",
        "Day of the Dead": "亡灵节",
        "Día de los Muertos": "亡灵节",
        "Día de la Raza": "种族日",
        "Día de La Rioja": "里奥哈日",
        "Día de la Constitución": "宪法日",
        "Boxing Day": "节礼日",
        "Remembrance Day": "阵亡将士纪念日",
        "Armistice Day": "停战日",
        "St. Stephen's Day": "圣斯蒂芬日",
        "Black Friday": "黑色星期五",
        "Cyber Monday": "网络星期一",
    }
    if name in holiday_map:
        return holiday_map[name]
    translated = translate_text_to_zh(
        name,
        state=state,
        diagnostics=diagnostics,
        cache_namespace="holiday",
        record_errors=False,
    )
    # 只有真正翻译出中文时才返回翻译结果，否则返回原名
    if translated != name and has_cjk(translated):
        return translated
    return name


def contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    return any(keyword_matches(text, keyword) for keyword in keywords)


def matched_keywords(text: str, keywords: tuple[str, ...] | list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword_matches(text, keyword)]


def business_relevance_score(section: str, text: str) -> tuple[float, list[str]]:
    lowered = text.lower()
    score = 0.0
    reasons: list[str] = []

    core_matches = matched_keywords(lowered, BUSINESS_CORE_KEYWORDS)
    if core_matches:
        score += min(8.0, len(core_matches) * 1.4)
        reasons.append("业务核心词: " + ", ".join(core_matches[:5]))

    vanso_matches = matched_keywords(lowered, VANSO_RELEVANCE_KEYWORDS)
    if vanso_matches:
        score += min(4.0, len(vanso_matches) * 1.0)
        reasons.append("Vanso 相关: " + ", ".join(vanso_matches[:4]))

    vizasound_matches = matched_keywords(lowered, VIZASOUND_RELEVANCE_KEYWORDS)
    if vizasound_matches:
        score += min(5.0, len(vizasound_matches) * 1.2)
        reasons.append("Vizasound 相关: " + ", ".join(vizasound_matches[:4]))

    if section == "head_releases":
        if contains_any(lowered, HEAD_RELEASE_INCLUDE):
            score += 3.0
            reasons.append("发行动态")
        if matched_keywords(lowered, HEAD_RELEASE_PRIORITY_ARTISTS):
            score += 3.0
            reasons.append("头部艺人")

    if section == "music_ai_industry":
        if contains_any(lowered, ("royalty", "rights", "licensing", "copyright", "subscription", "distribution",
                                  "ai", "artificial intelligence", "music tech", "generative", "deepfake",
                                  "sync", "publishing", "label", "dsp", "catalog", "acquisition",
                                  "startup", "funding", "valuation", "streaming platform")):
            score += 3.0
            reasons.append("版权/分发/订阅/AI产业")

    if section == "social_trends":
        if contains_any(lowered, ("tiktok", "reels", "shorts", "viral", "challenge", "meme")) and contains_any(
            lowered,
            ("song", "music", "sound", "audio", "dance", "remix", "creator", "ai"),
        ):
            score += 4.0
            reasons.append("短内容传播")
        if contains_any(lowered, SOCIAL_FUN_KEYWORDS):
            score += 2.2
            reasons.append("可玩社媒话题")

    if section == "culture_art":
        if contains_any(lowered, ("soundtrack", "film score", "composer", "music video", "concert film", "musical", "song")):
            score += 4.0
            reasons.append("影音音乐联动")
        if contains_any(lowered, ("film", "movie", "cinema", "documentary", "animation", "anime")):
            score += 1.4
            reasons.append("影视内容")
        if contains_any(lowered, ("tv", "series", "showrunner", "streaming series")):
            score += 1.2
            reasons.append("剧集内容")
        if contains_any(lowered, ("horror", "sci-fi", "fantasy", "thriller", "superhero", "video game adaptation")):
            score += 1.2
            reasons.append("类型片/游戏改编")
        if contains_any(lowered, ("adaptation", "prequel", "sequel", "remake", "reboot", "franchise")):
            score += 1.2
            reasons.append("IP 延展")
        if contains_any(lowered, ("actor", "actress", "director", "filmmaker", "screenwriter", "producer", "cast", "auteur")):
            score += 1.0
            reasons.append("主创/演员动态")
        if contains_any(lowered, ("festival", "cannes", "sundance", "venice", "berlin", "toronto", "tribeca", "sxsw", "locarno", "miffest")):
            score += 1.4
            reasons.append("影展/文化节")
        if contains_any(lowered, ("art", "artist", "gallery", "museum", "exhibition", "installation", "contemporary art")):
            score += 1.2
            reasons.append("艺术展览")
        if contains_any(lowered, CULTURE_FUN_KEYWORDS):
            score += 2.8
            reasons.append("文化借势潜力")

    if section == "politics":
        if contains_any(lowered, ("ai", "copyright", "licensing", "platform", "tiktok", "youtube", "trade", "tariff")):
            score += 4.0
            reasons.append("平台/政策影响")

    low_value_matches = matched_keywords(lowered, LOW_VALUE_KEYWORDS)
    if low_value_matches:
        score -= min(5.0, len(low_value_matches) * 1.5)
        reasons.append("低价值词: " + ", ".join(low_value_matches[:3]))

    return score, reasons


def passes_business_gate(section: str, text: str, business_score: float) -> bool:
    min_score = SECTION_MIN_BUSINESS_SCORES.get(section, 5.0)
    if business_score < min_score:
        return False
    if section == "politics":
        # 政治新闻不要求与业务强绑定，只要通过 min_score 即可入选
        return True
    if section == "social_trends":
        # 高分纯病毒事件（business_score≥7.5）直接通过，无需命中特定词
        if business_score >= 7.5:
            return True
        return contains_any(
            text,
            (
                "music",
                "song",
                "sound",
                "audio",
                "dance",
                "remix",
                "creator",
                "ai",
                "viral",
                "meme",
                "reaction",
                "debate",
                "fandom",
                "parody",
                "easter egg",
                "celebrity",
                "concert",
                "drama",
                "beef",
                "feud",
                "cancel",
                "controversy",
                "backlash",
                "fan",
                "discourse",
                "cringe",
                "wholesome",
                "stan",
                "trend",
                "tiktok",
                "instagram",
                "twitter",
                "youtube",
                "reddit",
                "challenge",
            ),
        )
    if section == "culture_art":
        return contains_any(
            text,
            (
                "music",
                "song",
                "soundtrack",
                "film score",
                "composer",
                "music video",
                "musical",
                "film",
                "movie",
                "tv",
                "trailer",
                "festival",
                "art",
                "museum",
                "exhibition",
                "documentary",
                "visual",
            ),
        )
    if section == "music_ai_industry":
        # AI 产业动向：business_score ≥ 1.0 即可直接通过（已在上方 min_score 校验）
        # 额外放宽：若文章明确涉及 AI / 音乐产业关键词，也放行
        return True
    return True


def infer_release_tag(text: str) -> str:
    lowered = text.lower()
    if keyword_matches(lowered, "tour") or keyword_matches(lowered, "tour dates"):
        return "巡演"
    if keyword_matches(lowered, "festival") or keyword_matches(lowered, "lineup"):
        return "音乐节"
    if keyword_matches(lowered, "playlist") or keyword_matches(lowered, "setlist"):
        return "歌单"
    if keyword_matches(lowered, "live show") or keyword_matches(lowered, "live performance") or keyword_matches(lowered, "live debut") or keyword_matches(lowered, "premiere"):
        return "现场"
    if keyword_matches(lowered, "music video") or keyword_matches(lowered, "video") or keyword_matches(lowered, "mv") or keyword_matches(lowered, "visual"):
        return "MV"
    if keyword_matches(lowered, "album") or re.search(r"\bep\b|\blp\b", lowered):
        return "专辑"
    if keyword_matches(lowered, "teaser") or keyword_matches(lowered, "trailer") or keyword_matches(lowered, "pre-save"):
        return "预热"
    return "新歌"


def infer_music_news_tag(text: str) -> str:
    lowered = text.lower()
    if keyword_matches(lowered, "tour"):
        return "巡演"
    if keyword_matches(lowered, "festival"):
        return "音乐节"
    if keyword_matches(lowered, "chart"):
        return "榜单"
    if keyword_matches(lowered, "album") or keyword_matches(lowered, "single"):
        return "发行动态"
    return "行业资讯"


def infer_ai_tag(text: str) -> str:
    lowered = text.lower()
    if keyword_matches(lowered, "price") or keyword_matches(lowered, "pricing") or keyword_matches(lowered, "subscription"):
        return "订阅价格"
    if keyword_matches(lowered, "ai") or keyword_matches(lowered, "artificial intelligence"):
        return "AI"
    if keyword_matches(lowered, "streaming"):
        return "流媒体"
    return "产业"


def infer_social_tag(text: str) -> str:
    lowered = text.lower()
    if keyword_matches(lowered, "meme"):
        return "Meme"
    if keyword_matches(lowered, "viral"):
        return "Viral"
    if keyword_matches(lowered, "tiktok"):
        return "TikTok"
    if keyword_matches(lowered, "instagram"):
        return "Instagram"
    return "平台热议"


def infer_culture_tag(text: str) -> str:
    lowered = text.lower()
    if keyword_matches(lowered, "soccer") or keyword_matches(lowered, "football"):
        return "足球"
    if keyword_matches(lowered, "film") or keyword_matches(lowered, "movie") or keyword_matches(lowered, "trailer"):
        return "电影"
    if keyword_matches(lowered, "art") or keyword_matches(lowered, "museum") or keyword_matches(lowered, "exhibition"):
        return "艺术"
    return "跨界文化"


def infer_politics_tag(text: str) -> str:
    lowered = text.lower()
    if keyword_matches(lowered, "election"):
        return "选举"
    if keyword_matches(lowered, "war"):
        return "地缘政治"
    if keyword_matches(lowered, "tariff") or keyword_matches(lowered, "trade"):
        return "政策"
    return "政治热点"


def item_tag(section: str, text: str) -> str:
    if section == "head_releases":
        return infer_release_tag(text)
    if section == "music_news":
        return infer_music_news_tag(text)
    if section == "music_ai_industry":
        return infer_ai_tag(text)
    if section == "social_trends":
        return infer_social_tag(text)
    if section == "culture_art":
        return infer_culture_tag(text)
    if section == "politics":
        return infer_politics_tag(text)
    return "动态"


def item_age_in_days(item_dt: datetime | None, report_dt: datetime) -> float:
    if item_dt is None:
        return 999.0
    delta = report_dt - item_dt.astimezone(report_dt.tzinfo)
    return delta.total_seconds() / 86400


def score_item(source: FeedSource, item: dict[str, Any], report_dt: datetime) -> float:
    text = f"{item['title']} {item['summary']}".lower()
    age_days = max(item_age_in_days(item["published_at"], report_dt), 0)
    freshness = max(0.0, 20.0 - age_days * 8.0)
    keyword_bonus = 0.0
    if source.include_keywords:
        keyword_bonus += sum(
            1.8 for keyword in source.include_keywords if keyword_matches(text, keyword)
        )
    if source.exclude_keywords:
        keyword_bonus -= sum(
            2.5 for keyword in source.exclude_keywords if keyword_matches(text, keyword)
        )
    if source.section == "head_releases":
        keyword_bonus += sum(
            6.0 for artist in HEAD_RELEASE_PRIORITY_ARTISTS if keyword_matches(text, artist)
        )
    return source.priority + freshness + keyword_bonus


def filter_items_for_source(
    source: FeedSource, feed_items: list[dict[str, Any]], report_dt: datetime
) -> list[NewsItem]:
    selected: list[NewsItem] = []
    for item in feed_items:
        title = item["title"]
        summary = item["summary"]
        link = item["link"]
        if not title or not link:
            continue

        full_text = f"{title} {summary}"
        include_text = (
            full_text
            if source.section in {"social_trends", "music_ai_industry"} or source.key.endswith("_head_release")
            else full_text
        )
        if source.include_keywords and not contains_any(include_text, source.include_keywords):
            continue
        if source.exclude_keywords and contains_any(full_text, source.exclude_keywords):
            continue

        if source.key == "billboard" and "/music/" not in link:
            continue
        if source.key == "billboard_head_release" and "/music/" not in link:
            continue
        if source.key == "mashable" and not contains_any(full_text, source.include_keywords):
            continue
        if source.key == "mbw" and not contains_any(full_text, source.include_keywords):
            continue
        if source.key.endswith("_head_release") and contains_any(
            full_text,
            (
                "cancel concert",
                "hospitalized",
                "shot",
                "critic",
                "statement",
                "lawsuit",
                "prison release",
                "release from prison",
            ),
        ):
            continue

        if not is_item_in_report_window(item["published_at"], report_dt):
            continue

        age_days = item_age_in_days(item["published_at"], report_dt)
        if age_days > source.max_age_days:
            continue

        if source.section == "head_releases" and not contains_any(full_text, HEAD_RELEASE_INCLUDE):
            if not source.key.endswith("_head_release"):
                continue

        business_score, score_reasons = business_relevance_score(source.section, full_text)
        if not passes_business_gate(source.section, full_text, business_score):
            continue

        tag = item_tag(source.section, full_text)
        score = score_item(source, item, report_dt) + business_score
        selected.append(
            NewsItem(
                source_key=source.key,
                source_name=source.name,
                section=source.section,
                title=title,
                link=link,
                summary=summary,
                published_at=item["published_at"],
                priority=source.priority,
                tag=tag,
                score=score,
                business_score=business_score,
                score_reasons=score_reasons,
            )
        )

    selected.sort(
        key=lambda item: (
            item.score,
            item.published_at.timestamp() if item.published_at else 0,
        ),
        reverse=True,
    )

    unique: list[NewsItem] = []
    seen: set[str] = set()
    for item in selected:
        dedupe_key = hashlib.md5(
            f"{item.section}|{normalize_title_key(item.title)}".encode("utf-8")
        ).hexdigest()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        unique.append(item)
        if len(unique) >= source.max_items:
            break
    return unique


def audit_feed_item(source: FeedSource, item: dict[str, Any], report_dt: datetime) -> dict[str, Any]:
    full_text = f"{item.get('title', '')} {item.get('summary', '')}"
    business_score, reasons = business_relevance_score(source.section, full_text)
    published_at = item.get("published_at")
    in_window = is_item_in_report_window(published_at, report_dt)
    return {
        "source_key": source.key,
        "source_name": source.name,
        "section": source.section,
        "section_title": SECTION_TITLES.get(source.section, source.section),
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "published_at": published_at.isoformat() if published_at else "",
        "in_report_window": in_window,
        "business_score": round(business_score, 2),
        "score_reasons": reasons,
    }


def audit_news_item(item: NewsItem) -> dict[str, Any]:
    return {
        "source_key": item.source_key,
        "source_name": item.source_name,
        "section": item.section,
        "section_title": SECTION_TITLES.get(item.section, item.section),
        "title": item.title,
        "cn_title": display_item_title(item),
        "link": item.link,
        "published_at": item.published_at.isoformat() if item.published_at else "",
        "tag": item.tag,
        "score": round(item.score, 2),
        "business_score": round(item.business_score, 2),
        "score_reasons": item.score_reasons or [],
    }


def fetch_section_items(
    report_dt: datetime,
    diagnostics: list[str],
    audit: dict[str, Any] | None = None,
) -> dict[str, list[NewsItem]]:
    sections: dict[str, list[NewsItem]] = {
        section: []
        for section in SECTION_TITLES
        if section not in {"holiday_events", "ops_suggestions"}
    }

    if audit is not None:
        audit.setdefault("raw_candidates", [])
        audit.setdefault("filtered_candidates", [])
        audit.setdefault("scored_candidates", [])
        audit.setdefault("final_selected", [])

    def process_source(source: FeedSource) -> tuple[str, list[NewsItem], list[dict[str, Any]], str | None]:
        try:
            feed_text = fetch_text(source.url)
            feed_items = parse_feed_items(feed_text)
            raw_items = [audit_feed_item(source, item, report_dt) for item in feed_items]
            items = filter_items_for_source(source, feed_items, report_dt)
            return source.section, items, raw_items, None
        except (
            urllib.error.URLError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            ET.ParseError,
            TimeoutError,
            ValueError,
        ) as exc:
            return source.section, [], [], f"{source.name} 抓取失败: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_source, source) for source in FEED_SOURCES]
        for future in concurrent.futures.as_completed(futures):
            section, items, raw_items, error = future.result()
            if audit is not None:
                audit["raw_candidates"].extend(raw_items)
                audit["filtered_candidates"].extend(audit_news_item(item) for item in items)
            sections[section].extend(items)
            if error:
                diagnostics.append(error)

    for section, items in sections.items():
        items.sort(
            key=lambda item: (
                item.score,
                item.published_at.timestamp() if item.published_at else 0,
            ),
            reverse=True,
        )
        deduped: list[NewsItem] = []
        seen_titles: set[str] = set()
        for item in items:
            title_key = normalize_title_key(item.title)
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            deduped.append(item)
        section_limit = SECTION_LIMITS.get(section, 3)
        sections[section] = deduped[:section_limit]
        if audit is not None:
            audit["scored_candidates"].extend(audit_news_item(item) for item in deduped)
            audit["final_selected"].extend(audit_news_item(item) for item in sections[section])
    return sections


def fetch_holiday_items(
    report_date: date,
    state: dict[str, Any],
    diagnostics: list[str],
) -> dict[str, list[dict[str, Any]]]:
    grouped_items: dict[str, list[dict[str, Any]]] = {"today": [], "week": [], "advance": []}

    years = [report_date.year]
    if report_date.month >= 11:
        years.append(report_date.year + 1)

    def fetch_country_holidays(country: str, year: int) -> tuple[list[dict[str, Any]], str | None]:
        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
        try:
            data = fetch_json(url, timeout=12)
        except (
            urllib.error.URLError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            return [], f"Nager.Date {country}-{year} 抓取失败: {exc}"
        return data, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(fetch_country_holidays, country, year)
            for country in HOLIDAY_COUNTRIES
            for year in years
        ]
        for future in concurrent.futures.as_completed(futures):
            data, error = future.result()
            if error:
                diagnostics.append(error)
                continue
            for holiday in data:
                country = holiday.get("countryCode")
                holiday_date = date.fromisoformat(holiday["date"])
                days_left = (holiday_date - report_date).days
                # 展示范围：今天(0)、未来7天、以及25-35天预警
                if not (0 <= days_left <= 7 or 25 <= days_left <= 35):
                    continue
                name = holiday.get("localName") or holiday.get("name")
                english_name = holiday.get("name") or ""
                holiday_text = f"{name} {english_name}"
                # 宽松过滤：只要能匹配任一关键词，或 days_left==0（今日节日必须显示）
                if days_left > 0 and not contains_any(holiday_text, HOLIDAY_VALUE_KEYWORDS):
                    continue
                if days_left == 0:
                    bucket = "today"
                elif days_left <= 7:
                    bucket = "week"
                else:
                    bucket = "advance"
                action = (
                    "今天是节日当天，建议今天确认社媒祝福推文、专题页和本地化 Push。"
                    if days_left == 0
                    else (
                        "今天就要确认倒计时文案、专题页封面与本地社媒发布时间。"
                        if days_left <= 7
                        else "适合启动节日歌单、情绪化选题和本地化物料排期。"
                    )
                )
                grouped_items[bucket].append(
                    {
                        "country": country,
                        "country_name": COUNTRY_NAMES.get(country, country),
                        "name": name,
                        "name_cn": translate_holiday_name(name, state, diagnostics),
                        "english_name": english_name,
                        "date": holiday_date,
                        "days_left": days_left,
                        "tag": "今日节日" if days_left == 0 else ("7天内提醒" if days_left <= 7 else "25-35天预警"),
                        "source_name": "Nager.Date",
                        "link": f"https://date.nager.at/api/v3/PublicHolidays/{holiday_date.year}/{country}",
                        "recommended_action": action,
                    }
                )

    for bucket, bucket_items in grouped_items.items():
        bucket_items.sort(key=lambda item: (item["days_left"], item["country"]))
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in bucket_items:
            key = f"{item['country']}|{item['date']}|{item['english_name']}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        # 今日节日最多8条，近期节日最多10条，预警最多6条
        limit = 8 if bucket == "today" else (10 if bucket == "week" else 6)
        grouped_items[bucket] = unique[:limit]
    return grouped_items


def extract_price_offers(raw_html: str, plans: list[str]) -> list[str]:
    cleaned = clean_html(raw_html)
    offers: list[str] = []
    for plan in plans:
        pattern = re.compile(
            rf"({re.escape(plan)}[^$]{{0,80}}\$[0-9]+(?:\.[0-9]{{2}})?(?:[^A-Za-z0-9]{{0,10}}(?:/month|a month|/mo|per month))?)",
            re.I,
        )
        for match in pattern.finditer(cleaned):
            offer = normalize_whitespace(match.group(1))
            if offer not in offers:
                offers.append(offer)
                break

    if offers:
        return offers

    generic = re.findall(
        r"([A-Za-z][A-Za-z\s]{0,30}\$[0-9]+(?:\.[0-9]{2})?(?:\s*(?:/month|a month|/mo|per month))?)",
        cleaned,
        flags=re.I,
    )
    deduped: list[str] = []
    for offer in generic:
        offer = normalize_whitespace(offer)
        if offer not in deduped:
            deduped.append(offer)
    return deduped[:6]


def fetch_price_alerts(
    report_dt: datetime, state: dict[str, Any], diagnostics: list[str]
) -> list[dict[str, Any]]:
    snapshots = state.setdefault("price_snapshots", {})
    alerts: list[dict[str, Any]] = []

    def process_tracker(tracker: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
        try:
            raw_html = fetch_text(tracker["url"])
        except (
            urllib.error.URLError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            return None, None, f"{tracker['name']} 抓取失败: {exc}"

        offers = extract_price_offers(raw_html, tracker["plans"])
        if not offers:
            return None, None, f"{tracker['name']} 未识别到价格结构"

        fingerprint = hashlib.sha256("\n".join(offers).encode("utf-8")).hexdigest()
        previous = snapshots.get(tracker["key"])
        alert: dict[str, Any] | None = None
        if previous and previous.get("fingerprint") != fingerprint:
            alert = {
                "service": tracker["name"],
                "tag": "订阅价格",
                "before": previous.get("offers", []),
                "after": offers,
                "captured_at": report_dt.isoformat(),
                "link": tracker["source_url"],
            }

        snapshot = {
            "key": tracker["key"],
            "service": tracker["name"],
            "offers": offers,
            "fingerprint": fingerprint,
            "captured_at": report_dt.isoformat(),
        }
        return alert, snapshot, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(process_tracker, tracker) for tracker in PRICE_TRACKERS]
        for future in concurrent.futures.as_completed(futures):
            alert, snapshot, error = future.result()
            if error:
                diagnostics.append(error)
            if alert:
                alerts.append(alert)
            if snapshot:
                snapshots[snapshot["key"]] = {
                    "service": snapshot["service"],
                    "offers": snapshot["offers"],
                    "fingerprint": snapshot["fingerprint"],
                    "captured_at": snapshot["captured_at"],
                }

    return alerts


def format_date_cn(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"


def format_report_date(value: date) -> str:
    return f"{value.year:04d}.{value.month:02d}.{value.day:02d}"


def format_date_short(value: date | None) -> str:
    if value is None:
        return ""
    return f"{value.month}/{value.day}"


def trim_title(title: str, max_len: int = 110) -> str:
    if len(title) <= max_len:
        return title
    return title[: max_len - 1].rstrip() + "…"


def display_item_title(item: NewsItem) -> str:
    # 优先中文标题，其次中文摘要（比英文标题好），最后才用英文标题
    if item.cn_title and has_cjk(item.cn_title):
        return normalize_whitespace(item.cn_title)
    if item.cn_summary and has_cjk(item.cn_summary):
        return normalize_whitespace(item.cn_summary)
    # 英文标题兜底：至少保证有内容
    return normalize_whitespace(item.title)


def markdown_source(item: NewsItem) -> str:
    return normalize_whitespace(item.source_name)


def concise_item_summary(item: NewsItem) -> str:
    # 只使用 cn_summary（来自 DeepL 翻译或 LLM 精选）
    # 不再回退到 heuristic_cn_summary（它只有标题，必然与标题重复）
    summary = normalize_whitespace(item.cn_summary) if item.cn_summary else ""
    if summary and not has_cjk(summary):
        summary = ""
    title = display_item_title(item)
    # 摘要与标题高度重复 → 置空（宁可没有摘要，也不要重复标题）
    if summary and title:
        if summary == title:
            summary = ""
        elif len(summary) <= len(title) + 8 and (summary.startswith(title[:12]) or title.startswith(summary[:12])):
            summary = ""
    return trim_title(summary, 72)


def default_why_it_matters(item: NewsItem) -> str:
    if item.section == "head_releases":
        return "可直接影响首页资源位、新歌提醒和艺人相关内容的点击效率。"
    if item.section == "music_ai_industry":
        return "涉及平台规则、版权、分发或 AI 工具能力，容易影响中短期运营判断。"
    if item.section == "social_trends":
        return "能帮助判断短视频平台的音频传播方向和内容模版。"
    return "适合做轻量借势或作为排期背景信息参考。"


def default_action_hint(item: NewsItem) -> str:
    if item.section == "head_releases":
        return "今天可同步准备推荐位、Push 和艺人页聚合素材。"
    if item.section == "music_ai_industry":
        return "今天可整理成一条平台观察，顺带校对站内相关话术。"
    if item.section == "social_trends":
        return "今天可拆出短视频脚本、BGM 推荐或跟梗文案模版。"
    return "今天可评估是否值得做借势图文、歌单或轻专题。"


def infer_social_platform(item: NewsItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    if "tiktok" in text:
        return "TikTok"
    if "instagram" in text or "reels" in text:
        return "Instagram / Reels"
    if "youtube" in text or "shorts" in text:
        return "YouTube / Shorts"
    return item.source_name


def infer_social_stage(item: NewsItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    if contains_any(text, ("surges", "viral", "breakout", "explodes", "trend")):
        return "上升 / 爆发"
    if contains_any(text, ("launch", "beta", "preview", "predict")):
        return "预热 / 观察"
    return "持续发酵"


def section_item_lines(item: NewsItem, mode: str) -> list[str]:
    title = trim_title(display_item_title(item), 48)
    summary = concise_item_summary(item)
    source = markdown_source(item)
    if summary:
        return [f"• **{title}** — {summary}（{source}）"]
    return [f"• **{title}**（{source}）"]


def holiday_group_title(bucket: str) -> str:
    if bucket == "today":
        return "今日节日"
    if bucket == "week":
        return "7天内提醒"
    return "25-35天预警"


def holiday_to_markdown_line(item: dict[str, Any]) -> str:
    original_name = item["name"]
    name_cn = item.get("name_cn") or ""
    country = item["country_name"]
    date_str = format_date_short(item["date"])
    days_left = item["days_left"]
    if days_left == 0:
        timing = f"{date_str}（今天）"
    elif days_left == 1:
        timing = f"{date_str}（明天）"
    else:
        timing = f"{date_str}（D-{days_left}）"
    # 同时显示原名和中文翻译（当两者不同时）
    if name_cn and name_cn != original_name:
        display_name = f"{original_name}（{name_cn}）"
    else:
        display_name = original_name
    return f"• **{display_name}·{country}** — {timing}"


def price_alert_to_markdown_line(item: dict[str, Any]) -> str:
    before = " / ".join(item["before"]) if item["before"] else "无历史快照"
    after = " / ".join(item["after"])
    return f"• **{item['service']} 订阅价格变化** — 旧价格：{before}；当前价格：{after} ([{item['service']}]({item['link']}))"


def fallback_action_plan(
    report_date: date,
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
) -> dict[str, list[str]]:
    plan = {
        "app_actions": [],
        "social_actions": [],
        "localization_actions": [],
        "watchouts": [],
    }

    if sections["head_releases"]:
        item = sections["head_releases"][0]
        plan["app_actions"].append(
            f"围绕“{trim_title(display_item_title(item), 34)}”安排首页推荐位、站内 Banner 和新歌提醒。"
        )
    if sections["music_ai_industry"]:
        item = sections["music_ai_industry"][0]
        plan["app_actions"].append(
            f"把“{trim_title(display_item_title(item), 34)}”转成一条平台观察或创作者教程选题，补到下午内容池。"
        )
    if sections["social_trends"]:
        item = sections["social_trends"][0]
        plan["social_actions"].append(
            f"围绕“{trim_title(display_item_title(item), 34)}”拆 1 条短视频脚本和 1 版跟梗文案，优先试 TikTok / IG Reels。"
        )
    if sections["culture_art"]:
        item = sections["culture_art"][0]
        plan["social_actions"].append(
            f"把“{trim_title(display_item_title(item), 34)}”转成跨界 BGM 或影视联动内容，适合晚间发一条轻量图文。"
        )
    if holidays["advance"]:
        holiday = holidays["advance"][0]
        plan["localization_actions"].append(
            f"为 {holiday['country_name']} 的 {holiday.get('name_cn') or holiday['name']} 提前准备节日歌单、封面和本地化 Push。"
        )
    if holidays["week"] or holidays["today"]:
        urgent_items = holidays["today"] or holidays["week"]
        holiday = urgent_items[0]
        plan["localization_actions"].append(
            f"{holiday['country_name']} 的 {holiday.get('name_cn') or holiday['name']} 已进入 D-{holiday['days_left']}，今天就要敲定倒计时文案和上线时间。"
        )
    if price_alerts:
        item = price_alerts[0]
        plan["watchouts"].append(
            f"{item['service']} 价格已变化，记得同步检查转化文案、对比页和社媒话术。"
        )
    if sections["politics"]:
        item = sections["politics"][0]
        plan["watchouts"].append(
            f"“{trim_title(display_item_title(item), 30)}”只适合轻量借势，建议保持中性语气，避免过度政治化表达。"
        )

    if not any(plan.values()):
        plan["watchouts"].append(
            f"{format_date_cn(report_date)} 暂无高优先级海外事件，建议维持常规发行观察与 24 小时热点轮巡。"
        )
    return {key: value[:3] for key, value in plan.items()}


def generate_action_plan(
    report_date: date,
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
    state: dict[str, Any],
    diagnostics: list[str],
) -> dict[str, list[str]]:
    fallback = fallback_action_plan(report_date, sections, holidays, price_alerts)
    if not llm_is_configured():
        return fallback

    serialized_holidays = {
        bucket: [
            {
                **item,
                "date": format_date_cn(item["date"]),
            }
            for item in bucket_items
        ]
        for bucket, bucket_items in holidays.items()
        if bucket in ("today", "week", "advance")
    }
    payload = {
        "report_date": format_date_cn(report_date),
        "head_releases": [
            {"title": display_item_title(item), "summary": item.cn_summary, "market": item.market_hint}
            for item in sections["head_releases"][:3]
        ],
        "music_ai_industry": [
            {"title": display_item_title(item), "summary": item.cn_summary, "market": item.market_hint}
            for item in sections["music_ai_industry"][:3]
        ],
        "social_trends": [
            {"title": display_item_title(item), "summary": item.cn_summary, "market": item.market_hint}
            for item in sections["social_trends"][:3]
        ],
        "holidays": serialized_holidays,
        "price_alerts": price_alerts[:2],
        "output_schema": {
            "app_actions": ["1-2条字符串，每条不超过45字"],
            "social_actions": ["1-2条字符串，每条不超过45字"],
            "localization_actions": ["0-1条字符串，每条不超过45字"],
            "watchouts": ["0-1条字符串，每条不超过45字"],
        },
    }
    system_prompt = (
        "你是海外音乐平台运营负责人。"
        "请把当日资讯整理成极简运营建议，输出简体中文 JSON。"
        "只输出字符串数组，不要对象，不要 priority/time_window/owner/details/success_check。"
        "每条一句话，短、直接、能执行。总建议数控制在 3 到 5 条。"
    )
    result = call_llm_json(system_prompt, payload, state, diagnostics, "action_plan")
    if not result:
        return fallback

    plan: dict[str, list[str]] = {}
    for key in ("app_actions", "social_actions", "localization_actions", "watchouts"):
        raw_items = result.get(key, [])
        if not isinstance(raw_items, list):
            plan[key] = fallback[key]
            continue
        cleaned = [normalize_action_plan_text(item) for item in raw_items]
        cleaned = [item for item in cleaned if item]
        plan[key] = cleaned[:3] or fallback[key]
    return plan


def build_top_signals(
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
) -> list[str]:
    candidates: list[tuple[float, str]] = []
    for section, weight in (
        ("head_releases", 4.0),
        ("music_ai_industry", 3.6),
        ("social_trends", 3.2),
    ):
        if sections[section]:
            item = sections[section][0]
            line = f"{SECTION_TITLES[section]}：{trim_title(display_item_title(item), 38)}"
            if item.why_it_matters:
                line += f"；{trim_title(item.why_it_matters, 36)}"
            candidates.append((item.score + weight, line))
    if price_alerts:
        candidates.append(
            (
                95.0,
                f"平台价格：{price_alerts[0]['service']} 价格快照出现变化，适合今天检查转化文案。",
            )
        )
    if holidays["week"] or holidays["today"]:
        urgent_items = holidays["today"] or holidays["week"]
        holiday = urgent_items[0]
        candidates.append(
            (
                94.0 - holiday["days_left"],
                f"节庆临期：{holiday['country_name']} 的 {holiday.get('name_cn') or holiday['name']} 进入 D-{holiday['days_left']} 窗口。",
            )
        )
    if holidays["advance"]:
        holiday = holidays["advance"][0]
        candidates.append(
            (
                85.0 - holiday["days_left"] / 2,
                f"节庆预警：{holiday['country_name']} 的 {holiday.get('name_cn') or holiday['name']} 距今 {holiday['days_left']} 天，可启动排期。",
            )
        )
    candidates.sort(key=lambda value: value[0], reverse=True)
    return [line for _, line in candidates[:3]]


def normalize_action_plan_text(item: Any) -> str:
    if isinstance(item, dict):
        risk = normalize_whitespace(str(item.get("risk", "")))
        today_action = normalize_whitespace(str(item.get("today_action", "")))
        action = normalize_whitespace(str(item.get("action", "")))
        if risk and today_action:
            return trim_title(f"{risk}；{today_action}", 70)
        if action:
            return trim_title(action, 60)
        for key in ("suggestion", "title", "scene"):
            value = normalize_whitespace(str(item.get(key, "")))
            if value:
                return trim_title(value, 60)
        return ""
    if isinstance(item, list):
        return trim_title("；".join(normalize_whitespace(str(part)) for part in item if normalize_whitespace(str(part))), 60)
    return trim_title(normalize_whitespace(str(item)), 60)


def action_plan_to_markdown_lines(action_plan: dict[str, list[str]]) -> list[str]:
    section_labels = [
        ("app_actions", "App内动作"),
        ("social_actions", "社媒动作"),
        ("localization_actions", "本地化动作"),
        ("watchouts", "注意事项"),
    ]
    lines: list[str] = []
    for key, label in section_labels:
        items = [normalize_action_plan_text(item) for item in action_plan.get(key, [])]
        items = [item for item in items if item]
        if not items:
            continue
        for item in items[:2]:
            lines.append(f"• **{label}** — {item}")
    return lines


def holiday_lines(holidays: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for bucket in ("today", "week", "advance"):
        items = holidays.get(bucket, [])
        if not items:
            continue
        lines.append(f"  {holiday_group_title(bucket)}")
        lines.extend(f"  {holiday_to_markdown_line(item)}" for item in items)
    return lines


def build_card_payload(
    report_dt: datetime,
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
    action_plan: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    report_label = format_report_date(report_dt.date())
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": (
                f"**海外运营每日舆情播报 | {report_label}**\n"
                "本播报聚焦 AI 音乐、AI 视频、短内容传播、版权分发、创作者经济与影音联动。"
            ),
        }
    ]

    for section in REPORT_SECTION_ORDER:
        if section == "ops_suggestions":
            continue  # 单独处理
        lines: list[str] = []
        if section == "holiday_events":
            lines.extend(holiday_lines(holidays))
        elif section == "music_ai_industry":
            for item in sections.get(section, []):
                lines.extend(section_item_lines(item, "standard"))
            lines.extend(price_alert_to_markdown_line(item) for item in price_alerts)
        else:
            for item in sections.get(section, []):
                lines.extend(section_item_lines(item, "standard"))

        if not lines:
            continue

        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "markdown",
                "content": f"【{SECTION_TITLES[section]}】\n" + "\n".join(lines),
            }
        )

    # 运营建议板块
    if action_plan:
        op_lines = action_plan_to_markdown_lines(action_plan)
        if op_lines:
            elements.append({"tag": "hr"})
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"【{SECTION_TITLES['ops_suggestions']}】\n" + "\n".join(op_lines),
                }
            )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": f"海外运营每日舆情播报 | {report_label}"},
            },
            "elements": elements,
        },
    }


def build_console_preview(
    report_dt: datetime,
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
    diagnostics: list[str],
    action_plan: dict[str, list[str]] | None = None,
) -> str:
    blocks = [f"海外运营每日舆情播报 | {format_report_date(report_dt.date())}"]

    for section in REPORT_SECTION_ORDER:
        if section == "ops_suggestions":
            continue  # 单独处理
        blocks.append(f"\n【{SECTION_TITLES[section]}】")
        if section == "holiday_events":
            lines = holiday_lines(holidays)
            if lines:
                blocks.extend(lines)
            else:
                blocks.append("- 今日无节庆信息")
            continue
        if section == "music_ai_industry":
            if sections.get(section):
                for item in sections[section]:
                    blocks.extend(section_item_lines(item, "standard"))
            if price_alerts:
                blocks.extend(price_alert_to_markdown_line(item) for item in price_alerts)
            if not sections[section] and not price_alerts:
                blocks.append("- 今日无高优先级条目")
            continue
        if sections.get(section):
            for item in sections[section]:
                blocks.extend(section_item_lines(item, "standard"))
        else:
            blocks.append("- 今日无高优先级条目")

    # 运营建议板块
    if action_plan:
        blocks.append(f"\n【{SECTION_TITLES['ops_suggestions']}】")
        blocks.extend(action_plan_to_markdown_lines(action_plan))

    blocks.append("\n本播报内容基于海外公开信源自动抓取、初筛、复筛和总编精选生成。")

    if diagnostics:
        blocks.append("\n【诊断信息】")
        blocks.extend(f"- {line}" for line in diagnostics)
    return "\n".join(blocks)


def count_report_items(
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
) -> int:
    news_count = sum(
        len(sections.get(section, []))
        for section in REPORT_SECTION_ORDER
        if section not in {"holiday_events", "ops_suggestions"}
    )
    holiday_count = sum(len(items) for items in holidays.values())
    return news_count + holiday_count + len(price_alerts)


def validate_report_quality(
    sections: dict[str, list[NewsItem]],
    holidays: dict[str, list[dict[str, Any]]],
    price_alerts: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    total_items = count_report_items(sections, holidays, price_alerts)
    if total_items == 0:
        errors.append("无合格条目，停止发送，避免硬凑低质量日报")
    if total_items > MAX_REPORT_ITEMS:
        errors.append(f"条目数 {total_items} 超过上限 {MAX_REPORT_ITEMS}")

    for section in REPORT_SECTION_ORDER:
        if section in {"holiday_events", "ops_suggestions"}:
            continue
        if len(sections.get(section, [])) > SECTION_LIMITS.get(section, 3):
            errors.append(f"{SECTION_TITLES[section]} 超过板块上限")
        for item in sections.get(section, []):
            if not item.source_name:
                errors.append(f"缺少信源: {item.title}")
            if len(section_item_lines(item, "standard")[0]) > 220:
                errors.append(f"条目过长: {display_item_title(item)}")
            if section in {"culture_art", "politics", "social_trends"}:
                text = f"{item.title} {item.summary} {item.cn_summary}"
                if not passes_business_gate(section, text, item.business_score):
                    errors.append(f"业务相关性不足: {display_item_title(item)}")
    return errors


def write_audit_files(audit: dict[str, Any]) -> None:
    ensure_data_dir()
    files = {
        "raw_candidates.json": audit.get("raw_candidates", []),
        "filtered_candidates.json": audit.get("filtered_candidates", []),
        "scored_candidates.json": audit.get("scored_candidates", []),
        "final_selected.json": audit.get("final_selected", []),
    }
    if audit.get("llm_selected"):
        files["llm_selected.json"] = audit["llm_selected"]
    if audit.get("quality_errors"):
        files["quality_errors.json"] = audit["quality_errors"]
    for filename, payload in files.items():
        (DATA_DIR / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="海外舆情自动监控并推送到飞书",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--send", action="store_true", help="推送到飞书 webhook")
    parser.add_argument("--dry-run", action="store_true", help="仅输出预览，不推送")
    parser.add_argument("--date", help="报告日期，格式 YYYY-MM-DD")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="报告时区")
    parser.add_argument("--webhook", help="飞书 webhook URL；默认读取 FEISHU_WEBHOOK_URL")
    parser.add_argument("--debug", action="store_true", help="输出诊断信息")
    parser.add_argument(
        "--skip-if-already-sent",
        action="store_true",
        help="如果当天已成功推送，则跳过本次发送",
    )
    return parser.parse_args()


def resolve_report_datetime(args: argparse.Namespace) -> datetime:
    try:
        tz = ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        if args.timezone == "Asia/Shanghai":
            tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
        else:
            raise
    if args.date:
        report_date = date.fromisoformat(args.date)
    else:
        report_date = datetime.now(tz).date()
    return datetime.combine(report_date, datetime.min.time(), tzinfo=tz) + timedelta(
        hours=DEFAULT_REPORT_HOUR,
        minutes=DEFAULT_REPORT_MINUTE,
    )


def main() -> int:
    args = parse_args()
    if not args.send and not args.dry_run:
        args.dry_run = True

    report_dt = resolve_report_datetime(args)
    diagnostics: list[str] = []
    state = load_state()
    if not llm_is_configured():
        diagnostics.append(
            "LLM 未配置，当前使用规则复筛与简洁摘要。可通过 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL 启用总编精选。"
        )

    audit: dict[str, Any] = {
        "report_date": report_dt.date().isoformat(),
        "raw_candidates": [],
        "filtered_candidates": [],
        "scored_candidates": [],
        "final_selected": [],
    }
    sections = fetch_section_items(report_dt, diagnostics, audit=audit)
    holidays = fetch_holiday_items(report_dt.date(), state, diagnostics)
    enrich_items_with_llm(sections, state, diagnostics)
    price_alerts = fetch_price_alerts(report_dt, state, diagnostics)
    sections = editorial_select_sections(sections, state, diagnostics, audit=audit)
    action_plan = generate_action_plan(report_dt.date(), sections, holidays, price_alerts, state, diagnostics)
    audit["final_selected"] = [
        audit_news_item(item)
        for section in REPORT_SECTION_ORDER
        if section not in {"holiday_events", "ops_suggestions"}
        for item in sections.get(section, [])
    ]
    quality_errors = validate_report_quality(sections, holidays, price_alerts)
    if quality_errors:
        audit["quality_errors"] = quality_errors
        diagnostics.extend(f"质量闸门: {error}" for error in quality_errors)
    save_state(state)
    ensure_data_dir()
    write_audit_files(audit)

    preview = build_console_preview(
        report_dt=report_dt,
        sections=sections,
        holidays=holidays,
        price_alerts=price_alerts,
        diagnostics=diagnostics if args.debug else [],
        action_plan=action_plan,
    )
    payload = build_card_payload(report_dt, sections, holidays, price_alerts, action_plan=action_plan)
    (DATA_DIR / "last_report.md").write_text(preview, encoding="utf-8")
    (DATA_DIR / "last_card.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(preview)

    if args.send:
        if quality_errors:
            print("\n质量闸门未通过，已停止发送。", file=sys.stderr)
            return 4

        delivery_state = state.setdefault("delivery", {})
        report_date_str = report_dt.date().isoformat()
        if args.skip_if_already_sent and delivery_state.get("last_sent_date") == report_date_str:
            print(f"\n{report_date_str} 已成功推送过，跳过本次重复发送。")
            return 0

        webhook = args.webhook or os.environ.get("FEISHU_WEBHOOK_URL")
        if not webhook:
            print("\n缺少飞书 webhook，请通过 --webhook 或 FEISHU_WEBHOOK_URL 提供。", file=sys.stderr)
            return 2

        try:
            response = post_json(webhook, payload)
        except (
            urllib.error.URLError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ) as exc:
            print(f"\n飞书推送失败: {exc}", file=sys.stderr)
            return 3

        print("\nFeishu response:")
        print(json.dumps(response, ensure_ascii=False, indent=2))
        delivery_state["last_sent_date"] = report_date_str
        delivery_state["last_sent_at"] = datetime.now(ZoneInfo(args.timezone)).isoformat()
        save_state(state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
