"""数据库模型定义 - 使用 SQLAlchemy ORM"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    Enum as SQLEnum, ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy import event
import enum
from decimal import Decimal


Base = declarative_base()


# ==================== AInsight Pro 枚举类型 ====================

class KOLTierEnum(enum.Enum):
    """KOL 等级"""
    GOD = "god"           # 行业顶级人物 (Karpathy, Yann LeCun)
    EXPERT = "expert"     # 知名从业者 (大厂 AI 负责人)
    INSIDER = "insider"   # 业内人士 (AI 公司员工)
    OBSERVER = "observer" # 关注者 (二手信息传播者)


class SourceTypeEnum(enum.Enum):
    """内容来源类型"""
    X_POST = "x_post"
    GITHUB_REPO = "github_repo"
    GITHUB_RELEASE = "github_release"
    BLOG_POST = "blog_post"
    PAPER = "paper"
    NEWS = "news"


class IntelCategoryEnum(enum.Enum):
    """情报类型"""
    MODEL_RELEASE = "model_release"
    FUNDING = "funding"
    PRODUCT_LAUNCH = "product_launch"
    RESEARCH = "research"
    DRAMA = "drama"
    TUTORIAL = "tutorial"
    MARKET_SIGNAL = "market_signal"


class ImpactLevelEnum(enum.Enum):
    """影响级别"""
    PARADIGM_SHIFT = "paradigm_shift"
    SIGNIFICANT = "significant"
    INCREMENTAL = "incremental"
    NOISE = "noise"


class TimeSensitivityEnum(enum.Enum):
    """时效性"""
    ACT_NOW = "act_now"
    WATCH_CLOSELY = "watch_closely"
    BACKGROUND = "background"


class EraEnum(enum.Enum):
    """AI 时代"""
    PRE_TRANSFORMER = "pre_transformer"
    GPT_ERA = "gpt_era"
    MULTIMODAL_ERA = "multimodal_era"
    AGENT_ERA = "agent_era"
    EMBODIED_ERA = "embodied_era"


class MilestoneTypeEnum(enum.Enum):
    """里程碑类型"""
    BREAKTHROUGH = "breakthrough"
    ITERATION = "iteration"
    ECOSYSTEM = "ecosystem"
    CONTROVERSY = "controversy"


class RelationTypeEnum(enum.Enum):
    """情报关联类型"""
    PREDECESSOR = "predecessor"
    SUCCESSOR = "successor"
    COMPETITOR = "competitor"
    ENABLER = "enabler"


class TopicStatusEnum(enum.Enum):
    """主题状态"""
    ACTIVE = "active"       # 活跃，持续收集内容
    MERGED = "merged"       # 已合并到其他主题
    ARCHIVED = "archived"   # 已归档


class CategoryEnum(enum.Enum):
    """新闻分类"""
    TECH = "科技"
    POLITICS = "政治"
    ECONOMY = "经济"
    SOCIETY = "社会"
    INTERNATIONAL = "国际"
    SPORTS = "体育"
    ENTERTAINMENT = "娱乐"
    OTHER = "其他"


class RegionEnum(enum.Enum):
    """新闻区域"""
    CHINA = "中国"
    WORLD = "世界"


class NewsSource(Base):
    """新闻源表"""
    __tablename__ = "news_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="新闻源名称")
    url = Column(String(500), nullable=False, comment="RSS/API URL")
    region = Column(SQLEnum(RegionEnum), nullable=False, comment="区域")
    source_type = Column(String(20), default="rss", comment="类型: rss/api/web")
    enabled = Column(Boolean, default=True, comment="是否启用")

    # 抓取配置
    fetch_interval = Column(Integer, default=3600, comment="抓取间隔(秒)")
    max_items = Column(Integer, default=10, comment="每次最大抓取数")
    last_fetch_at = Column(DateTime, comment="上次抓取时间")

    # 元数据
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    articles = relationship("NewsArticle", back_populates="source")
    fetch_logs = relationship("FetchLog", back_populates="source")

    def __repr__(self):
        return f"<NewsSource(name='{self.name}', region='{self.region.value}')>"


class NewsArticle(Base):
    """新闻文章表"""
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 基本信息
    title = Column(String(500), nullable=False, comment="标题")
    url = Column(String(1000), nullable=False, comment="原文链接")
    url_hash = Column(String(64), nullable=False, unique=True, comment="URL哈希(去重)")

    # 内容
    content = Column(Text, comment="原文内容")
    summary = Column(Text, comment="AI摘要")

    # 分类
    category = Column(SQLEnum(CategoryEnum), default=CategoryEnum.OTHER, comment="分类")
    region = Column(SQLEnum(RegionEnum), nullable=False, comment="区域")

    # 来源
    source_id = Column(Integer, ForeignKey("news_sources.id"), nullable=False)
    source_name = Column(String(100), nullable=False, comment="来源名称(冗余)")

    # 时间
    published_at = Column(DateTime, comment="发布时间")
    fetched_at = Column(DateTime, server_default=func.now(), comment="抓取时间")
    processed_at = Column(DateTime, comment="AI处理时间")

    # 状态
    is_processed = Column(Boolean, default=False, comment="是否已AI处理")
    is_sent = Column(Boolean, default=False, comment="是否已推送")
    sent_at = Column(DateTime, comment="推送时间")

    # 元数据 (存储原始数据)
    raw_data = Column(JSON, comment="原始数据")

    # 索引
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    source = relationship("NewsSource", back_populates="articles")

    __table_args__ = (
        Index("idx_articles_category", "category"),
        Index("idx_articles_region", "region"),
        Index("idx_articles_published", "published_at"),
        Index("idx_articles_processed", "is_processed"),
        Index("idx_articles_sent", "is_sent"),
        Index("idx_articles_source", "source_id"),
    )

    def __repr__(self):
        return f"<NewsArticle(title='{self.title[:30]}...', category='{self.category.value}')>"


class FetchLog(Base):
    """抓取日志表"""
    __tablename__ = "fetch_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("news_sources.id"), nullable=False)

    # 抓取结果
    status = Column(String(20), nullable=False, comment="状态: success/failed")
    items_fetched = Column(Integer, default=0, comment="抓取数量")
    items_new = Column(Integer, default=0, comment="新增数量")
    error_message = Column(Text, comment="错误信息")

    # 时间
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
    duration_ms = Column(Integer, comment="耗时(毫秒)")

    # 关系
    source = relationship("NewsSource", back_populates="fetch_logs")

    __table_args__ = (
        Index("idx_fetch_logs_source", "source_id"),
        Index("idx_fetch_logs_status", "status"),
        Index("idx_fetch_logs_started", "started_at"),
    )


class User(Base):
    """用户表 (为WebUI准备)"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 认证信息
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    # Telegram 绑定
    telegram_chat_id = Column(String(50), unique=True, comment="Telegram Chat ID")
    telegram_username = Column(String(100), comment="Telegram 用户名")

    # 状态
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    # 时间
    created_at = Column(DateTime, server_default=func.now())
    last_login_at = Column(DateTime)

    # 关系
    subscriptions = relationship("UserSubscription", back_populates="user")

    def __repr__(self):
        return f"<User(username='{self.username}')>"


class UserSubscription(Base):
    """用户订阅配置表"""
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 订阅配置
    categories = Column(JSON, comment="订阅的分类列表")
    regions = Column(JSON, comment="订阅的区域列表")
    sources = Column(JSON, comment="订阅的新闻源ID列表")

    # 推送配置
    push_enabled = Column(Boolean, default=True, comment="是否启用推送")
    push_times = Column(JSON, comment="推送时间配置")
    max_items_per_push = Column(Integer, default=10, comment="每次推送最大数量")

    # 时间
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    user = relationship("User", back_populates="subscriptions")

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_subscription"),
    )


# ==================== AInsight Pro 新增表 ====================

class KOLRoleEnum(enum.Enum):
    """KOL 角色"""
    RESEARCHER = "researcher"       # 研究员/科学家
    ENGINEER = "engineer"           # 工程师/开发者
    FOUNDER = "founder"             # 创始人/CEO
    INVESTOR = "investor"           # 投资人/VC
    JOURNALIST = "journalist"       # 记者/媒体人
    EDUCATOR = "educator"           # 教育者/讲师
    ANALYST = "analyst"             # 分析师
    INFLUENCER = "influencer"       # 意见领袖/博主


class KOL(Base):
    """KOL 表 - 关键意见领袖"""
    __tablename__ = "kols"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 基本信息
    name = Column(String(100), nullable=False, comment="显示名称")
    handle = Column(String(100), unique=True, nullable=False, comment="唯一标识 (@karpathy)")
    platform = Column(String(20), default="x", comment="平台: x/github/blog")
    avatar_url = Column(String(500), comment="头像 URL")
    is_verified = Column(Boolean, default=False, comment="是否认证账号（蓝V）")
    bio = Column(Text, comment="简介")

    # 角色
    role = Column(SQLEnum(KOLRoleEnum), default=KOLRoleEnum.INFLUENCER, comment="KOL 角色")

    # 等级与权重
    tier = Column(SQLEnum(KOLTierEnum), default=KOLTierEnum.OBSERVER, comment="KOL 等级")
    credibility_score = Column(Float, default=0.5, comment="可信度评分 0-1")
    weight = Column(Float, default=1.0, comment="聚类权重 0.1-10.0")

    # 社交数据
    followers = Column(Integer, default=0, comment="粉丝数")
    following = Column(Integer, default=0, comment="关注数")

    # RSS 订阅 (新增)
    rss_url = Column(String(500), comment="RSS 订阅地址 (Nitter/RSSHub)")

    # 状态
    is_active = Column(Boolean, default=True, comment="是否活跃追踪")
    last_fetched_at = Column(DateTime, comment="上次抓取时间")

    # 元数据
    extra_data = Column(JSON, comment="额外数据")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    raw_contents = relationship("RawContent", back_populates="kol")

    __table_args__ = (
        Index("idx_kols_tier", "tier"),
        Index("idx_kols_platform", "platform"),
        Index("idx_kols_handle", "handle"),
        Index("idx_kols_role", "role"),
        Index("idx_kols_followers", "followers"),
    )

    def __repr__(self):
        return f"<KOL(handle='{self.handle}', tier='{self.tier.value}')>"


class Topic(Base):
    """主题表 - 聚类后的主题"""
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 主题信息
    title = Column(String(200), nullable=False, comment="主题标题")
    slug = Column(String(100), unique=True, nullable=False, comment="URL 友好标识")
    description = Column(Text, comment="主题描述")

    # 关键词 (用于 FTS 匹配)
    keywords = Column(Text, comment="关键词，空格分隔")

    # 分类
    category = Column(SQLEnum(IntelCategoryEnum), comment="情报类型")
    tags = Column(JSON, comment="标签列表")

    # 热度
    heat_score = Column(Integer, default=0, comment="热度评分 1-100")
    source_count = Column(Integer, default=0, comment="关联的原始内容数量")

    # 状态
    status = Column(SQLEnum(TopicStatusEnum), default=TopicStatusEnum.ACTIVE, comment="主题状态")
    merged_into_id = Column(Integer, ForeignKey("topics.id"), comment="合并到的主题 ID")

    # 时间
    first_seen_at = Column(DateTime, comment="首次发现时间")
    last_updated_at = Column(DateTime, comment="最后更新时间")
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    raw_contents = relationship("RawContent", back_populates="topic")
    intelligence_package = relationship("IntelligencePackage", back_populates="topic", uselist=False)
    merged_topics = relationship("Topic", backref="merged_into", remote_side=[id])

    __table_args__ = (
        Index("idx_topics_category", "category"),
        Index("idx_topics_status", "status"),
        Index("idx_topics_heat", "heat_score"),
        Index("idx_topics_slug", "slug"),
    )

    def __repr__(self):
        return f"<Topic(title='{self.title[:30]}...', status='{self.status.value}')>"


class RawContent(Base):
    """原始内容表 - 抓取的原始数据"""
    __tablename__ = "raw_contents"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 来源信息
    source_type = Column(SQLEnum(SourceTypeEnum), nullable=False, comment="来源类型")
    source_url = Column(String(1000), nullable=False, comment="原始链接")
    source_url_hash = Column(String(64), unique=True, nullable=False, comment="URL 哈希去重")

    # KOL 关联
    kol_id = Column(Integer, ForeignKey("kols.id"), comment="关联的 KOL")

    # 作者信息（冗余存储，便于显示）
    author_name = Column(String(100), comment="作者显示名称")
    author_handle = Column(String(100), comment="作者用户名 (@xxx)")
    author_avatar = Column(String(500), comment="作者头像 URL")
    is_verified = Column(Boolean, default=False, comment="是否认证账号（蓝V）")

    # 内容
    title = Column(String(500), comment="标题")
    text_content = Column(Text, nullable=False, comment="文本内容")
    media_urls = Column(JSON, comment="媒体 URL 列表")
    code_snippet = Column(Text, comment="代码片段")

    # 互动数据
    likes = Column(Integer, default=0)
    retweets = Column(Integer, default=0)
    replies = Column(Integer, default=0)
    stars = Column(Integer, default=0, comment="GitHub stars")
    forks = Column(Integer, default=0, comment="GitHub forks")

    # 主题关联
    topic_id = Column(Integer, ForeignKey("topics.id"), comment="关联的主题")
    relevance_score = Column(Float, default=0.0, comment="与主题的相关度 0-1")

    # 处理状态
    is_clustered = Column(Boolean, default=False, comment="是否已聚类")
    is_synthesized = Column(Boolean, default=False, comment="是否已合成到情报包")

    # 时间
    published_at = Column(DateTime, comment="发布时间")
    fetched_at = Column(DateTime, server_default=func.now(), comment="抓取时间")
    clustered_at = Column(DateTime, comment="聚类时间")

    # 原始数据
    raw_data = Column(JSON, comment="原始 JSON 数据")
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    kol = relationship("KOL", back_populates="raw_contents")
    topic = relationship("Topic", back_populates="raw_contents")

    __table_args__ = (
        Index("idx_raw_contents_source_type", "source_type"),
        Index("idx_raw_contents_kol", "kol_id"),
        Index("idx_raw_contents_topic", "topic_id"),
        Index("idx_raw_contents_clustered", "is_clustered"),
        Index("idx_raw_contents_published", "published_at"),
    )

    def __repr__(self):
        return f"<RawContent(type='{self.source_type.value}', url='{self.source_url[:50]}...')>"


class IntelligencePackage(Base):
    """情报包表 - AI 合成的高密度情报"""
    __tablename__ = "intelligence_packages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 唯一标识
    intel_id = Column(String(100), unique=True, nullable=False, comment="情报包 ID (intel_20240219_xxx)")

    # 主题关联
    topic_id = Column(Integer, ForeignKey("topics.id"), unique=True, nullable=False, comment="关联的主题")

    # 合成内容 (JSON 存储完整的 synthesis 对象)
    tldr = Column(String(200), comment="一句话结论")
    fact_summary = Column(JSON, comment="事实摘要 {what, who, when, scale}")
    action_guide = Column(JSON, comment="行动指南 {for_developers, for_investors, pitfalls}")
    logic_chain = Column(JSON, comment="逻辑推演链")
    historical_context = Column(JSON, comment="历史关联")
    verdict = Column(JSON, comment="综合判断 {impact_level, time_sensitivity, analyst_note}")

    # 时间轴
    event_date = Column(DateTime, comment="事件日期")
    era = Column(SQLEnum(EraEnum), comment="所属时代")
    milestone_type = Column(SQLEnum(MilestoneTypeEnum), comment="里程碑类型")

    # 元数据
    source_count = Column(Integer, default=0, comment="合成的原始来源数量")
    kol_count = Column(Integer, default=0, comment="涉及的 KOL 数量")
    synthesis_model = Column(String(50), default="qwen-plus", comment="合成使用的模型")

    # 状态
    is_published = Column(Boolean, default=False, comment="是否已发布")
    published_at = Column(DateTime, comment="发布时间")

    # 时间
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    topic = relationship("Topic", back_populates="intelligence_package")
    intel_sources = relationship("IntelSource", back_populates="intelligence_package")
    relations_from = relationship("IntelRelation", foreign_keys="IntelRelation.from_intel_id", back_populates="from_intel")
    relations_to = relationship("IntelRelation", foreign_keys="IntelRelation.to_intel_id", back_populates="to_intel")

    __table_args__ = (
        Index("idx_intel_packages_intel_id", "intel_id"),
        Index("idx_intel_packages_era", "era"),
        Index("idx_intel_packages_published", "is_published"),
        Index("idx_intel_packages_event_date", "event_date"),
    )

    def __repr__(self):
        return f"<IntelligencePackage(intel_id='{self.intel_id}')>"


class IntelSource(Base):
    """情报来源关联表 - 情报包与原始内容的关联"""
    __tablename__ = "intel_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联
    intel_id = Column(Integer, ForeignKey("intelligence_packages.id"), nullable=False)
    raw_content_id = Column(Integer, ForeignKey("raw_contents.id"), nullable=False)

    # 排序与权重
    display_order = Column(Integer, default=0, comment="展示顺序")
    relevance_score = Column(Float, default=0.0, comment="相关度评分")
    is_primary = Column(Boolean, default=False, comment="是否为主要来源")

    # 时间
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    intelligence_package = relationship("IntelligencePackage", back_populates="intel_sources")
    raw_content = relationship("RawContent")

    __table_args__ = (
        UniqueConstraint("intel_id", "raw_content_id", name="uq_intel_source"),
        Index("idx_intel_sources_intel", "intel_id"),
        Index("idx_intel_sources_raw", "raw_content_id"),
    )


class IntelRelation(Base):
    """情报关联表 - 情报包之间的关系"""
    __tablename__ = "intel_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联
    from_intel_id = Column(Integer, ForeignKey("intelligence_packages.id"), nullable=False)
    to_intel_id = Column(Integer, ForeignKey("intelligence_packages.id"), nullable=False)

    # 关系类型
    relation_type = Column(SQLEnum(RelationTypeEnum), nullable=False, comment="关联类型")
    description = Column(String(200), comment="关系描述")

    # 时间
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    from_intel = relationship("IntelligencePackage", foreign_keys=[from_intel_id], back_populates="relations_from")
    to_intel = relationship("IntelligencePackage", foreign_keys=[to_intel_id], back_populates="relations_to")

    __table_args__ = (
        UniqueConstraint("from_intel_id", "to_intel_id", "relation_type", name="uq_intel_relation"),
        Index("idx_intel_relations_from", "from_intel_id"),
        Index("idx_intel_relations_to", "to_intel_id"),
    )


# ==================== SQLite FTS 全文搜索支持 ====================

# FTS 虚拟表需要通过原生 SQL 创建，这里提供创建函数
def create_fts_tables(engine):
    """创建 SQLite FTS5 全文搜索虚拟表"""
    from sqlalchemy import text

    with engine.connect() as conn:
        # 主题 FTS 表
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(
                title,
                description,
                keywords,
                content='topics',
                content_rowid='id'
            )
        """))

        # 原始内容 FTS 表
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS raw_contents_fts USING fts5(
                title,
                text_content,
                content='raw_contents',
                content_rowid='id'
            )
        """))

        # 创建触发器保持 FTS 同步 - Topics
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS topics_ai AFTER INSERT ON topics BEGIN
                INSERT INTO topics_fts(rowid, title, description, keywords)
                VALUES (new.id, new.title, new.description, new.keywords);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS topics_ad AFTER DELETE ON topics BEGIN
                INSERT INTO topics_fts(topics_fts, rowid, title, description, keywords)
                VALUES ('delete', old.id, old.title, old.description, old.keywords);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS topics_au AFTER UPDATE ON topics BEGIN
                INSERT INTO topics_fts(topics_fts, rowid, title, description, keywords)
                VALUES ('delete', old.id, old.title, old.description, old.keywords);
                INSERT INTO topics_fts(rowid, title, description, keywords)
                VALUES (new.id, new.title, new.description, new.keywords);
            END
        """))

        # 创建触发器保持 FTS 同步 - RawContents
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS raw_contents_ai AFTER INSERT ON raw_contents BEGIN
                INSERT INTO raw_contents_fts(rowid, title, text_content)
                VALUES (new.id, new.title, new.text_content);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS raw_contents_ad AFTER DELETE ON raw_contents BEGIN
                INSERT INTO raw_contents_fts(raw_contents_fts, rowid, title, text_content)
                VALUES ('delete', old.id, old.title, old.text_content);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS raw_contents_au AFTER UPDATE ON raw_contents BEGIN
                INSERT INTO raw_contents_fts(raw_contents_fts, rowid, title, text_content)
                VALUES ('delete', old.id, old.title, old.text_content);
                INSERT INTO raw_contents_fts(rowid, title, text_content)
                VALUES (new.id, new.title, new.text_content);
            END
        """))

        conn.commit()


def search_topics_fts(session, query: str, limit: int = 10):
    """搜索主题 (FTS)"""
    from sqlalchemy import text
    result = session.execute(
        text("""
            SELECT t.* FROM topics t
            JOIN topics_fts fts ON t.id = fts.rowid
            WHERE topics_fts MATCH :query
            ORDER BY rank
            LIMIT :limit
        """),
        {"query": query, "limit": limit}
    )
    return result.fetchall()


def search_raw_contents_fts(session, query: str, limit: int = 10):
    """搜索原始内容 (FTS)"""
    from sqlalchemy import text
    result = session.execute(
        text("""
            SELECT rc.* FROM raw_contents rc
            JOIN raw_contents_fts fts ON rc.id = fts.rowid
            WHERE raw_contents_fts MATCH :query
            ORDER BY rank
            LIMIT :limit
        """),
        {"query": query, "limit": limit}
    )
    return result.fetchall()
