"""
导出 X/Twitter Cookie 工具

使用方法：
1. 在 Chrome 中登录 X (x.com)
2. 按 F12 打开开发者工具
3. 切换到 Application (应用) 标签
4. 左侧选择 Cookies -> https://x.com
5. 找到以下 Cookie 并复制值：
   - auth_token
   - ct0
   - twid (可选)

然后运行此脚本输入 Cookie 值。
"""
import json
import os

def main():
    print("=" * 60)
    print("X/Twitter Cookie 导出工具")
    print("=" * 60)
    print()
    print("请在 Chrome 中打开 x.com，按 F12 打开开发者工具")
    print("切换到 Application -> Cookies -> https://x.com")
    print("复制以下 Cookie 的值：")
    print()

    # 获取必需的 Cookie
    auth_token = input("auth_token: ").strip()
    if not auth_token:
        print("错误: auth_token 是必需的")
        return

    ct0 = input("ct0: ").strip()
    if not ct0:
        print("错误: ct0 是必需的")
        return

    twid = input("twid (可选，直接回车跳过): ").strip()

    # 构建 Cookie 列表
    cookies = [
        {
            "name": "auth_token",
            "value": auth_token,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        },
        {
            "name": "ct0",
            "value": ct0,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
    ]

    if twid:
        cookies.append({
            "name": "twid",
            "value": twid,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        })

    # 保存到文件
    config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
    os.makedirs(config_dir, exist_ok=True)

    cookie_file = os.path.join(config_dir, "x_cookies.json")
    with open(cookie_file, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ Cookie 已保存到: {cookie_file}")
    print()
    print("现在可以运行抓取:")
    print("  python ainsight.py --limit 5")


if __name__ == "__main__":
    main()
