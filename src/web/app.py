"""AInsight Web UI - FastAPI 应用"""
import os
import re
import httpx
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Query, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

from src.database import DatabaseService
from src.database.models import TopicStatusEnum, IntelCategoryEnum, KOL, KOLTierEnum, KOLRoleEnum

load_dotenv()

app = FastAPI(title="AInsight", description="AI 情报聚合器")

# 静态文件和模板
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 数据库
db: Optional[DatabaseService] = None

# Nitter 实例（用于生成 RSS URL）
NITTER_INSTANCE = "https://nitter.privacydev.net"


@app.on_event("startup")
async def startup():
    global db
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()


@app.on_event("shutdown")
async def shutdown():
    if db:
        await db.close()


# ==================== 页面路由 ====================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 - 情报概览"""
    from sqlalchemy import select, or_
    from src.database.models import RawContent

    # 获取统计
    stats = await db.get_clustering_stats()

    # 获取热门主题
    topics = await db.get_active_topics(limit=20)

    # 为每个主题获取情报包
    topics_with_intel = []
    for topic in topics:
        intel = await db.get_topic_intelligence(topic.id)
        topics_with_intel.append({
            "topic": topic,
            "intel": intel,
        })

    # 获取未关联主题的原文
    async with db.session() as session:
        result = await session.execute(
            select(RawContent).where(
                or_(RawContent.topic_id == None, RawContent.is_clustered == False)
            ).order_by(RawContent.published_at.desc()).limit(20)
        )
        unclustered_contents = result.scalars().all()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "topics_with_intel": topics_with_intel,
        "unclustered_contents": unclustered_contents,
        "now": datetime.now(),
    })


@app.get("/topics", response_class=HTMLResponse)
async def topics_page(
    request: Request,
    category: Optional[str] = None,
    sort: str = Query("heat", description="排序方式: heat/time/sources"),
    page: int = Query(1, ge=1),
):
    """主题列表页"""
    limit = 20
    offset = (page - 1) * limit

    # 解析分类
    cat_enum = None
    if category:
        try:
            cat_enum = IntelCategoryEnum(category)
        except ValueError:
            pass

    topics = await db.get_active_topics(category=cat_enum, limit=limit, offset=offset, sort_by=sort)

    # 分类列表
    categories = [
        {"value": "model_release", "label": "模型发布", "emoji": "🚀"},
        {"value": "funding", "label": "融资消息", "emoji": "💰"},
        {"value": "product_launch", "label": "产品发布", "emoji": "📦"},
        {"value": "research", "label": "研究论文", "emoji": "📚"},
        {"value": "drama", "label": "行业八卦", "emoji": "🎭"},
        {"value": "tutorial", "label": "教程分享", "emoji": "📖"},
        {"value": "market_signal", "label": "市场信号", "emoji": "📊"},
    ]

    return templates.TemplateResponse("topics.html", {
        "request": request,
        "topics": topics,
        "categories": categories,
        "current_category": category,
        "current_sort": sort,
        "page": page,
    })


@app.get("/topic/{topic_id}", response_class=HTMLResponse)
async def topic_detail(request: Request, topic_id: int):
    """主题详情页"""
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        return templates.TemplateResponse("404.html", {
            "request": request,
            "message": "主题不存在"
        }, status_code=404)

    # 获取相关内容
    contents = await db.get_topic_contents(topic_id)

    # 获取情报包
    intel = await db.get_topic_intelligence(topic_id)

    return templates.TemplateResponse("topic_detail.html", {
        "request": request,
        "topic": topic,
        "contents": contents,
        "intel": intel,
    })


@app.get("/intelligence", response_class=HTMLResponse)
async def intelligence_page(
    request: Request,
    page: int = Query(1, ge=1),
):
    """情报包列表页"""
    limit = 10
    offset = (page - 1) * limit

    intel_packages = await db.get_published_intelligence(limit=limit, offset=offset)

    # 获取关联的主题信息
    intel_with_topics = []
    for intel in intel_packages:
        topic = await db.get_topic_by_id(intel.topic_id)
        intel_with_topics.append({
            "intel": intel,
            "topic": topic,
        })

    return templates.TemplateResponse("intelligence.html", {
        "request": request,
        "intel_list": intel_with_topics,
        "page": page,
    })


# ==================== API 路由 ====================

@app.get("/api/stats")
async def api_stats():
    """获取统计数据"""
    return await db.get_clustering_stats()


@app.get("/api/topics")
async def api_topics(
    category: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
):
    """获取主题列表"""
    cat_enum = None
    if category:
        try:
            cat_enum = IntelCategoryEnum(category)
        except ValueError:
            pass

    topics = await db.get_active_topics(category=cat_enum, limit=limit, offset=offset)

    result = []
    for t in topics:
        intel = await db.get_topic_intelligence(t.id)
        result.append({
            "id": t.id,
            "title": t.title,
            "category": t.category.value if t.category else None,
            "heat_score": t.heat_score,
            "source_count": t.source_count,
            "first_seen_at": t.first_seen_at.isoformat() if t.first_seen_at else None,
            "tldr": intel.tldr if intel else None,
        })

    return {"topics": result}


@app.get("/api/topic/{topic_id}")
async def api_topic_detail(topic_id: int):
    """获取主题详情"""
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        return {"error": "Topic not found"}

    contents = await db.get_topic_contents(topic_id)
    intel = await db.get_topic_intelligence(topic_id)

    return {
        "topic": {
            "id": topic.id,
            "title": topic.title,
            "category": topic.category.value if topic.category else None,
            "description": topic.description,
            "keywords": topic.keywords,
            "heat_score": topic.heat_score,
            "source_count": topic.source_count,
            "first_seen_at": topic.first_seen_at.isoformat() if topic.first_seen_at else None,
        },
        "contents": [
            {
                "id": c.id,
                "title": c.title,
                "text": c.text_content,
                "source_url": c.source_url,
                "source_type": c.source_type.value if c.source_type else None,
                "published_at": c.published_at.isoformat() if c.published_at else None,
                "media_urls": c.media_urls if c.media_urls else [],
                "author_name": c.author_name,
                "author_handle": c.author_handle,
                "author_avatar": c.author_avatar,
                "is_verified": getattr(c, 'is_verified', False),
                "kol_tier": c.raw_data.get('kol_tier', 'observer') if c.raw_data else 'observer',
                "likes": c.likes or 0,
                "retweets": c.retweets or 0,
                "replies": c.replies or 0,
                "raw_data": c.raw_data if c.raw_data else {},
            }
            for c in contents
        ],
        "intelligence": {
            "tldr": intel.tldr if intel else None,
            "fact_summary": intel.fact_summary if intel else None,
            "action_guide": intel.action_guide if intel else None,
            "verdict": intel.verdict if intel else None,
        } if intel else None,
    }


@app.get("/api/content/{content_id}")
async def api_content_detail(content_id: int):
    """获取单条原文详情"""
    from sqlalchemy import select
    from src.database.models import RawContent

    async with db.session() as session:
        result = await session.execute(
            select(RawContent).where(RawContent.id == content_id)
        )
        content = result.scalar_one_or_none()

        if not content:
            return {"error": "Content not found"}

        return {
            "content": {
                "id": content.id,
                "title": content.title,
                "text": content.text_content,
                "source_url": content.source_url,
                "source_type": content.source_type.value if content.source_type else None,
                "published_at": content.published_at.isoformat() if content.published_at else None,
                "media_urls": content.media_urls if content.media_urls else [],
                "author_name": content.author_name,
                "author_handle": content.author_handle,
                "author_avatar": content.author_avatar,
                "is_verified": getattr(content, 'is_verified', False),
                "kol_tier": content.raw_data.get('kol_tier', 'observer') if content.raw_data else 'observer',
                "likes": content.likes or 0,
                "retweets": content.retweets or 0,
                "replies": content.replies or 0,
                "raw_data": content.raw_data if content.raw_data else {},
            }
        }


# ==================== KOL 管理页面 ====================

@app.get("/kols", response_class=HTMLResponse)
async def kols_page(
    request: Request,
    tier: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
):
    """KOL 管理页面"""
    limit = 50
    offset = (page - 1) * limit

    # 构建查询
    from sqlalchemy import select, func as sql_func
    stmt = select(KOL)

    if tier:
        try:
            stmt = stmt.where(KOL.tier == KOLTierEnum(tier))
        except ValueError:
            pass

    # category 字段已删除，跳过筛选

    stmt = stmt.order_by(KOL.weight.desc(), KOL.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)

    async with db.session() as session:
        result = await session.execute(stmt)
        kols = result.scalars().all()

        # 统计
        count_stmt = select(sql_func.count(KOL.id))
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

    # 分类选项
    tiers = [
        {"value": "god", "label": "God Tier", "emoji": "👑"},
        {"value": "expert", "label": "Expert", "emoji": "🎯"},
        {"value": "insider", "label": "Insider", "emoji": "🔮"},
        {"value": "observer", "label": "Observer", "emoji": "👀"},
    ]

    categories = [
        {"value": "ai_researcher", "label": "AI 研究员", "emoji": "🔬"},
        {"value": "founder_ceo", "label": "创始人/CEO", "emoji": "🚀"},
        {"value": "vc_investor", "label": "投资人", "emoji": "💰"},
        {"value": "engineer", "label": "工程师", "emoji": "👨‍💻"},
        {"value": "journalist", "label": "记者/媒体", "emoji": "📰"},
        {"value": "influencer", "label": "KOL/博主", "emoji": "🎤"},
    ]

    return templates.TemplateResponse("kols.html", {
        "request": request,
        "kols": kols,
        "total": total,
        "tiers": tiers,
        "categories": categories,
        "current_tier": tier,
        "current_category": category,
        "page": page,
        "nitter_instance": NITTER_INSTANCE,
    })


# ==================== KOL API ====================

class KOLCreate(BaseModel):
    """创建 KOL 请求"""
    handle: str
    name: Optional[str] = None
    tier: str = "observer"
    role: Optional[str] = None
    category: Optional[str] = None
    weight: float = 1.0


class KOLUpdate(BaseModel):
    """更新 KOL 请求"""
    name: Optional[str] = None
    tier: Optional[str] = None
    role: Optional[str] = None
    category: Optional[str] = None
    weight: Optional[float] = None
    is_active: Optional[bool] = None


@app.get("/api/kols")
async def api_list_kols(
    tier: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """获取 KOL 列表"""
    from sqlalchemy import select

    stmt = select(KOL)

    if tier:
        try:
            stmt = stmt.where(KOL.tier == KOLTierEnum(tier))
        except ValueError:
            pass

    # category 字段已删除

    if is_active is not None:
        stmt = stmt.where(KOL.is_active == is_active)

    stmt = stmt.order_by(KOL.weight.desc()).offset(offset).limit(limit)

    async with db.session() as session:
        result = await session.execute(stmt)
        kols = result.scalars().all()

    return {
        "kols": [
            {
                "id": k.id,
                "handle": k.handle,
                "name": k.name,
                "tier": k.tier.value if k.tier else None,
                "role": k.role.value if k.role else None,
                "category": k.category.value if k.category else None,
                "weight": k.weight,
                "is_active": k.is_active,
                "rss_url": f"{NITTER_INSTANCE}/{k.handle}/rss" if k.handle else None,
            }
            for k in kols
        ]
    }


@app.post("/api/kols")
async def api_create_kol(kol_data: KOLCreate):
    """创建新 KOL"""
    from sqlalchemy import select

    handle = kol_data.handle.lstrip("@").strip()

    async with db.session() as session:
        # 检查是否已存在
        stmt = select(KOL).where(KOL.handle == handle)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=400, detail=f"KOL @{handle} 已存在")

        # 解析枚举
        try:
            tier = KOLTierEnum(kol_data.tier)
        except ValueError:
            tier = KOLTierEnum.OBSERVER

        role = None
        if kol_data.role:
            try:
                role = KOLRoleEnum(kol_data.role)
            except ValueError:
                pass

        # 创建 KOL
        kol = KOL(
            handle=handle,
            name=kol_data.name or handle,
            tier=tier,
            role=role,
            weight=kol_data.weight,
            rss_url=f"{NITTER_INSTANCE}/{handle}/rss",
            is_active=True,
        )

        session.add(kol)
        await session.flush()
        kol_id = kol.id
        kol_handle = kol.handle
        kol_name = kol.name
        kol_tier = kol.tier.value

    return {
        "success": True,
        "kol": {
            "id": kol_id,
            "handle": kol_handle,
            "name": kol_name,
            "tier": kol_tier,
        }
    }


@app.post("/api/kols/batch")
async def api_batch_create_kols(handles: List[str] = Form(...)):
    """批量导入 KOL"""
    from sqlalchemy import select

    created = []
    skipped = []

    async with db.session() as session:
        for raw_handle in handles:
            handle = raw_handle.lstrip("@").strip()
            if not handle:
                continue

            # 检查是否已存在
            stmt = select(KOL).where(KOL.handle == handle)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                skipped.append(handle)
                continue

            # 创建 KOL
            kol = KOL(
                handle=handle,
                name=handle,
                tier=KOLTierEnum.OBSERVER,
                weight=1.0,
                rss_url=f"{NITTER_INSTANCE}/{handle}/rss",
                is_active=True,
            )
            session.add(kol)
            created.append(handle)

    return {
        "success": True,
        "created": len(created),
        "skipped": len(skipped),
        "created_handles": created[:20],
        "skipped_handles": skipped[:10],
    }


@app.put("/api/kols/{kol_id}")
async def api_update_kol(kol_id: int, kol_data: KOLUpdate):
    """更新 KOL"""
    from sqlalchemy import select

    async with db.session() as session:
        stmt = select(KOL).where(KOL.id == kol_id)
        result = await session.execute(stmt)
        kol = result.scalar_one_or_none()

        if not kol:
            raise HTTPException(status_code=404, detail="KOL 不存在")

        # 更新字段
        if kol_data.name is not None:
            kol.name = kol_data.name

        if kol_data.tier is not None:
            try:
                kol.tier = KOLTierEnum(kol_data.tier)
            except ValueError:
                pass

        if kol_data.role is not None:
            try:
                kol.role = KOLRoleEnum(kol_data.role)
            except ValueError:
                pass

        # category 字段已删除

        if kol_data.weight is not None:
            kol.weight = kol_data.weight

        if kol_data.is_active is not None:
            kol.is_active = kol_data.is_active

        handle = kol.handle

    return {"success": True, "message": f"KOL @{handle} 已更新"}


@app.delete("/api/kols/{kol_id}")
async def api_delete_kol(kol_id: int):
    """删除 KOL"""
    from sqlalchemy import select

    async with db.session() as session:
        stmt = select(KOL).where(KOL.id == kol_id)
        result = await session.execute(stmt)
        kol = result.scalar_one_or_none()

        if not kol:
            raise HTTPException(status_code=404, detail="KOL 不存在")

        handle = kol.handle
        await session.delete(kol)

    return {"success": True, "message": f"KOL @{handle} 已删除"}


# ==================== 翻译 API ====================

class TranslateRequest(BaseModel):
    """翻译请求"""
    text: str
    target_lang: str = "en"  # en 或 zh


@app.post("/api/translate")
async def api_translate(req: TranslateRequest):
    """翻译文本 - 使用 Google Translate 免费 API"""
    text = req.text[:5000]  # 限制长度
    target = req.target_lang

    # 检测源语言
    # 简单判断：如果包含中文字符，源语言是中文
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))

    if target == "zh" and has_chinese:
        # 已经是中文，不需要翻译
        return {"translated": text, "source_lang": "zh", "target_lang": "zh"}
    elif target == "en" and not has_chinese:
        # 已经是英文，不需要翻译
        return {"translated": text, "source_lang": "en", "target_lang": "en"}

    source_lang = "zh" if has_chinese else "en"

    try:
        # 使用 Google Translate 免费 API
        async with httpx.AsyncClient(timeout=10) as client:
            # Google Translate 免费端点
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "sl": "zh-CN" if source_lang == "zh" else "en",
                "tl": "en" if target == "en" else "zh-CN",
                "dt": "t",
                "q": text
            }

            response = await client.get(url, params=params)
            response.raise_for_status()

            # 解析响应
            result = response.json()
            translated_text = ""
            if result and result[0]:
                for item in result[0]:
                    if item[0]:
                        translated_text += item[0]

            return {
                "translated": translated_text,
                "source_lang": source_lang,
                "target_lang": target
            }

    except Exception as e:
        # 翻译失败，返回原文
        return {
            "translated": text,
            "source_lang": source_lang,
            "target_lang": target,
            "error": str(e)
        }

