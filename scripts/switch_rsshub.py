"""
切换 RSSHub 配置脚本

用法:
    python scripts/switch_rsshub.py local   # 切换到本地 RSSHub
    python scripts/switch_rsshub.py public  # 切换到公共 RSSHub
    python scripts/switch_rsshub.py status  # 查看当前状态
"""
import sys
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

def switch_to_local(config):
    """切换到本地 RSSHub 并启用所有数据源"""
    config["rsshub"]["base_url"] = "http://localhost:1200"

    # 启用 AI KOL
    for kol in config.get("ai_kols", []):
        kol["enabled"] = True

    # 启用关键词搜索
    for kw in config.get("ai_keywords", []):
        kw["enabled"] = True

    # 启用 GitHub
    for gh in config.get("github", []):
        gh["enabled"] = True

    return config

def switch_to_public(config):
    """切换到公共 RSSHub 并禁用受限数据源"""
    config["rsshub"]["base_url"] = "https://rsshub.app"

    # 禁用 AI KOL（公共实例不支持）
    for kol in config.get("ai_kols", []):
        kol["enabled"] = False

    # 禁用关键词搜索
    for kw in config.get("ai_keywords", []):
        kw["enabled"] = False

    # 禁用 GitHub
    for gh in config.get("github", []):
        gh["enabled"] = False

    return config

def show_status(config):
    """显示当前配置状态"""
    base_url = config["rsshub"]["base_url"]
    is_local = "localhost" in base_url or "127.0.0.1" in base_url

    print(f"RSSHub: {base_url} ({'本地' if is_local else '公共'})")
    print()

    # 统计启用的数据源
    kol_enabled = sum(1 for k in config.get("ai_kols", []) if k.get("enabled"))
    kol_total = len(config.get("ai_kols", []))

    kw_enabled = sum(1 for k in config.get("ai_keywords", []) if k.get("enabled"))
    kw_total = len(config.get("ai_keywords", []))

    gh_enabled = sum(1 for g in config.get("github", []) if g.get("enabled"))
    gh_total = len(config.get("github", []))

    media_enabled = sum(1 for m in config.get("tech_media", []) if m.get("enabled"))
    media_total = len(config.get("tech_media", []))

    print(f"AI KOL:     {kol_enabled}/{kol_total} 启用")
    print(f"关键词搜索: {kw_enabled}/{kw_total} 启用")
    print(f"GitHub:     {gh_enabled}/{gh_total} 启用")
    print(f"科技媒体:   {media_enabled}/{media_total} 启用")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1].lower()
    config = load_config()

    if action == "local":
        config = switch_to_local(config)
        save_config(config)
        print("✅ 已切换到本地 RSSHub (http://localhost:1200)")
        print("   所有数据源已启用")
        print()
        print("请确保 RSSHub 已启动:")
        print("   docker-compose up -d rsshub")

    elif action == "public":
        config = switch_to_public(config)
        save_config(config)
        print("✅ 已切换到公共 RSSHub (https://rsshub.app)")
        print("   X/Twitter 和 GitHub 数据源已禁用")

    elif action == "status":
        show_status(config)

    else:
        print(f"未知操作: {action}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
