"""
契约层 (Contract Layer) - Pydantic Schema 定义

功能与作用：
1. 数据验证：自动验证 API 输入输出的数据格式和类型
2. 序列化：将 ORM 对象转换为 JSON 响应
3. 文档生成：自动生成 OpenAPI/Swagger 文档
4. 类型安全：提供 IDE 自动补全和类型检查
5. 前后端契约：明确定义 API 接口规范，前后端可独立开发

使用方式：
- Request Schema: 用于验证 API 请求参数
- Response Schema: 用于序列化 API 响应数据
- 在 FastAPI 路由中使用 response_model 参数指定响应 Schema
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ==================== 枚举类型 ====================

class KOLTierEnum(str, Enum):
    """KOL 等级"""
    GOD = "god"           # >= 5万粉丝
    EXPERT = "expert"     # >= 3万粉丝
    INSIDER = "insider"   # >= 1万粉丝
    OBSERVER = "observer" # < 1万粉丝


class SourceTypeEnum(str, Enum):
    """内容来源类型"""
    X_POST = "x_post"
    GITHUB_REPO = "github_repo"
    GITHUB_RELEASE = "github_release"
    BLOG_POST = "blog_post"
    PAPER = "paper"
    NEWS = "news"


class IntelCategoryEnum(str, Enum):
    """情报类型"""
    MODEL_RELEASE = "model_release"
    FUNDING = "funding"
    PRODUCT_LAUNCH = "product_launch"
    RESEARCH = "research"
    DRAMA = "drama"
    TUTORIAL = "tutorial"
    MARKET_SIGNAL = "market_signal"


class ImpactLevelEnum(str, Enum):
    """影响级别"""
    PARADIGM_SHIFT = "paradigm_shift"
    SIGNIFICANT = "significant"
    INCREMENTAL = "incremental"
    NOISE = "noise"


class TimeSensitivityEnum(str, Enum):
    """时效性"""
    ACT_NOW = "act_now"
    WATCH_CLOSELY = "watch_closely"
    BACKGROUND = "background"


# ==================== KOL 相关 Schema ====================

class KOLBase(BaseModel):
    """KOL 基础信息"""
    handle: str = Field(..., description="Twitter handle (@xxx)")
    name: Optional[str] = Field(None, description="显示名称")
    tier: KOLTierEnum = Field(KOLTierEnum.OBSERVER, description="KOL 等级")
    weight: float = Field(1.0, ge=0.1, le=5.0, description="聚类权重")


class KOLCreate(KOLBase):
    """创建 KOL 请求"""
    role: Optional[str] = Field(None, description="KOL 角色")


class KOLUpdate(BaseModel):
    """更新 KOL 请求"""
    name: Optional[str] = None
    tier: Optional[str] = None
    role: Optional[str] = None
    weight: Optional[float] = Field(None, ge=0.1, le=5.0)
    is_active: Optional[bool] = None


class KOLResponse(BaseModel):
    """KOL 响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    handle: str
    name: str
    platform: str
    avatar_url: Optional[str] = None
    is_verified: bool = False
    tier: str
    role: Optional[str] = None
    weight: float
    followers: int = 0
    is_active: bool = True
    created_at: Optional[datetime] = None


class KOLListResponse(BaseModel):
    """KOL 列表响应"""
    kols: List[KOLResponse]
    total: int
    page: int
    limit: int


# ==================== 原始内容 Schema ====================

class RawContentBase(BaseModel):
    """原始内容基础信息"""
    source_type: SourceTypeEnum
    source_url: str
    text_content: str
    title: Optional[str] = None


class RawContentResponse(BaseModel):
    """原始内容响应 - 用于前端显示"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str] = None
    text: str = Field(..., alias="text_content", description="文本内容")
    source_url: str
    source_type: Optional[str] = None
    published_at: Optional[datetime] = None

    # 作者信息
    author_name: Optional[str] = None
    author_handle: Optional[str] = None
    author_avatar: Optional[str] = None
    is_verified: bool = False
    kol_tier: str = "observer"

    # 互动数据
    likes: int = 0
    retweets: int = 0
    replies: int = 0

    # 媒体
    media_urls: List[str] = []

    # 原始数据（保留格式）
    raw_data: Dict[str, Any] = {}


# ==================== 主题 Schema ====================

class TopicBase(BaseModel):
    """主题基础信息"""
    title: str = Field(..., max_length=200)
    category: Optional[IntelCategoryEnum] = None
    description: Optional[str] = None


class TopicResponse(BaseModel):
    """主题响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    heat_score: int = 0
    source_count: int = 0
    status: str = "active"
    first_seen_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None


class TopicListResponse(BaseModel):
    """主题列表响应"""
    topics: List[TopicResponse]
    total: int


# ==================== 情报包 Schema ====================

class FactSummary(BaseModel):
    """事实摘要"""
    what: str = Field(..., description="发生了什么")
    who: str = Field(..., description="关键角色")
    when: str = Field(..., description="时间节点")
    scale: str = Field(..., description="规模数据")


class ActionGuide(BaseModel):
    """行动指南"""
    for_developers: List[str] = Field(default_factory=list, description="开发者行动建议")
    for_investors: List[str] = Field(default_factory=list, description="投资者关注点")
    pitfalls: List[str] = Field(default_factory=list, description="避坑指南")


class LogicChainItem(BaseModel):
    """逻辑推演链项"""
    premise: str = Field(..., description="前提")
    inference: str = Field(..., description="推断")
    confidence: str = Field("medium", description="置信度: high/medium/low")
    source_ids: List[int] = Field(default_factory=list, description="支持来源 ID")


class Verdict(BaseModel):
    """综合判断"""
    impact_level: ImpactLevelEnum = Field(..., description="影响级别")
    time_sensitivity: TimeSensitivityEnum = Field(..., description="时效性")
    analyst_note: str = Field(..., max_length=200, description="分析师点评")


class IntelligencePackageResponse(BaseModel):
    """情报包响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    intel_id: str
    topic_id: int

    # 合成内容
    tldr: Optional[str] = Field(None, description="一句话结论")
    fact_summary: Optional[FactSummary] = None
    action_guide: Optional[ActionGuide] = None
    logic_chain: List[LogicChainItem] = []
    verdict: Optional[Verdict] = None

    # 元数据
    source_count: int = 0
    kol_count: int = 0
    is_published: bool = False
    created_at: Optional[datetime] = None


# ==================== 组合响应 Schema ====================

class TopicDetailResponse(BaseModel):
    """主题详情响应（包含内容和情报）"""
    topic: TopicResponse
    contents: List[RawContentResponse]
    intelligence: Optional[IntelligencePackageResponse] = None


class HomePageResponse(BaseModel):
    """首页响应"""
    stats: Dict[str, Any]
    topics_with_intel: List[TopicDetailResponse]
    unclustered_contents: List[RawContentResponse]


# ==================== 通用响应 Schema ====================

class SuccessResponse(BaseModel):
    """成功响应"""
    success: bool = True
    message: str


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error: str
    detail: Optional[str] = None


class PaginatedResponse(BaseModel):
    """分页响应基类"""
    total: int
    page: int
    limit: int
    has_more: bool
