"""数据库模型定义 - 使用 SQLAlchemy ORM"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Enum as SQLEnum, ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum


Base = declarative_base()


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
