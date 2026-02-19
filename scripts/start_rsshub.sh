#!/bin/bash
# AInsight 启动脚本

set -e

echo "=========================================="
echo "AInsight - AI 情报聚合器"
echo "=========================================="

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

# 启动 RSSHub
echo ""
echo "📦 启动 RSSHub..."
docker-compose up -d rsshub

# 等待 RSSHub 启动
echo "⏳ 等待 RSSHub 启动..."
sleep 5

# 检查 RSSHub 状态
if curl -s http://localhost:1200 > /dev/null; then
    echo "✅ RSSHub 已启动: http://localhost:1200"
else
    echo "⚠️ RSSHub 可能还在启动中，请稍后检查"
fi

echo ""
echo "=========================================="
echo "下一步操作："
echo "1. 修改 config/sources.yaml 中的 rsshub.base_url 为 http://localhost:1200"
echo "2. 启用需要的数据源（将 enabled: false 改为 true）"
echo "3. 运行: python ainsight.py --test"
echo "=========================================="
