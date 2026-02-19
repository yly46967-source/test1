"""AInsight Web UI - FastAPI 应用"""
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from src.database import DatabaseService
from src.database.models import TopicStatusEnum, IntelCategoryEnum

load_dotenv()

app = FastAPI(title="AInsight", description="AI 情报聚合器")

# 静态文件和模板
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 数据库
db: Optional[DatabaseService] = None


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
    # 获取统计
    stats = await db.get_clustering_stats()

    # 获取热门主题
    topics = await db.get_active_topics(limit=10)

    # 为每个主题获取情报包
    topics_with_intel = []
    for topic in topics:
        intel = await db.get_topic_intelligence(topic.id)
        topics_with_intel.append({
            "topic": topic,
            "intel": intel,
        })

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "topics_with_intel": topics_with_intel,
        "now": datetime.now(),
    })


@app.get("/topics", response_class=HTMLResponse)
async def topics_page(
    request: Request,
    category: Optional[str] = None,
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

    topics = await db.get_active_topics(category=cat_enum, limit=limit, offset=offset)

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
        },
        "contents": [
            {
                "id": c.id,
                "title": c.title,
                "text": c.text_content,
                "source_url": c.source_url,
                "source_type": c.source_type.value if c.source_type else None,
                "published_at": c.published_at.isoformat() if c.published_at else None,
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
