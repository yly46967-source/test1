"""AInsight Web UI - FastAPI 应用"""
import os
from typing import Optional, List

from fastapi import FastAPI, Request, Query, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

from src.database import DatabaseService
from src.database.models import KOL, KOLTierEnum, KOLRoleEnum

load_dotenv()

app = FastAPI(title="AInsight", description="AI 情报聚合器")

# 静态文件和模板
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# 自定义 Jinja2 过滤器：格式化数字
def format_number(value):
    """格式化数字：1000+ 显示为 1.2k，1000000+ 显示为 1.2M"""
    if value is None:
        return "0"
    try:
        value = int(value)
    except (ValueError, TypeError):
        return "0"
    if value >= 1000000:
        return f"{value / 1000000:.1f}M"
    elif value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


# 自定义 Jinja2 过滤器：中文时间格式
def format_chinese_time(dt):
    """格式化时间为中文格式：上午1:40 · 2026年2月23日"""
    if dt is None:
        return ""
    try:
        hour = dt.hour
        if hour < 12:
            period = "上午"
            display_hour = hour if hour != 0 else 12
        else:
            period = "下午"
            display_hour = hour - 12 if hour != 12 else 12
        return f"{period}{display_hour}:{dt.minute:02d} · {dt.year}年{dt.month}月{dt.day}日"
    except (AttributeError, TypeError):
        return ""


templates.env.filters["format_number"] = format_number
templates.env.filters["format_chinese_time"] = format_chinese_time

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
    """首页 - MVP X风格三栏布局"""
    from sqlalchemy import select
    from src.database.models import RawContent, IntelligencePackage

    # 获取有价值的帖子（按评分排序，显示所有）
    async with db.session() as session:
        # 帖子 - 移除 limit 限制
        posts_result = await session.execute(
            select(RawContent)
            .where(RawContent.value_score > 0)
            .order_by(RawContent.value_score.desc())
        )
        posts = posts_result.scalars().all()

        # 情报
        intels_result = await session.execute(
            select(IntelligencePackage)
            .where(IntelligencePackage.is_published == True)
            .order_by(IntelligencePackage.published_at.desc())
            .limit(5)
        )
        intels = intels_result.scalars().all()

        # 为情报添加来源头像
        intels_with_avatars = []
        for intel in intels:
            # 获取相关帖子的头像
            if intel.topic_id:
                avatars_result = await session.execute(
                    select(RawContent.author_avatar)
                    .where(RawContent.topic_id == intel.topic_id)
                    .where(RawContent.author_avatar != None)
                    .limit(5)
                )
                avatars = [r[0] for r in avatars_result.fetchall() if r[0]]
            else:
                avatars = []

            intels_with_avatars.append({
                "tldr": intel.tldr,
                "signal": intel.signal or "",
                "shift": intel.shift or "",
                "alpha": intel.alpha or [],
                "source_count": intel.source_count,
                "source_avatars": avatars,
            })

    return templates.TemplateResponse("feed.html", {
        "request": request,
        "posts": posts,
        "intels": intels_with_avatars,
    })




# ==================== API 路由 ====================

@app.get("/api/stats")
async def api_stats():
    """获取统计数据"""
    return await db.get_clustering_stats()


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
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
):
    """获取 KOL 列表"""
    from sqlalchemy import select, func as sql_func

    stmt = select(KOL)
    count_stmt = select(sql_func.count(KOL.id))

    if tier:
        try:
            stmt = stmt.where(KOL.tier == KOLTierEnum(tier))
            count_stmt = count_stmt.where(KOL.tier == KOLTierEnum(tier))
        except ValueError:
            pass

    # category 字段已删除

    if is_active is not None:
        stmt = stmt.where(KOL.is_active == is_active)
        count_stmt = count_stmt.where(KOL.is_active == is_active)

    stmt = stmt.order_by(KOL.weight.desc()).offset(offset).limit(limit)

    async with db.session() as session:
        result = await session.execute(stmt)
        kols = result.scalars().all()

        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

    return {
        "kols": [
            {
                "id": k.id,
                "handle": k.handle,
                "name": k.name,
                "avatar_url": k.avatar_url,
                "tier": k.tier.value if k.tier else None,
                "role": k.role.value if k.role else None,
                "weight": k.weight,
                "is_active": k.is_active,
                "rss_url": f"{NITTER_INSTANCE}/{k.handle}/rss" if k.handle else None,
            }
            for k in kols
        ],
        "total": total,
        "limit": limit,
        "offset": offset
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

