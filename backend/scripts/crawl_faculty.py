"""院系师资爬虫脚本（占位）。

生产对接：Scrapy + Playwright 抓取师资页面。
"""

import argparse


def crawl(department: str, url: str) -> None:
    """抓取指定院系师资页面（占位）。"""
    print(f"[占位] 抓取 {department} 师资页面：{url}")
    print("生产期对接 Scrapy + Playwright，遵守 robots.txt 与校内网络中心规定")


def main() -> None:
    parser = argparse.ArgumentParser(description="师资页面爬虫")
    parser.add_argument("--department", default="自动化系", help="院系名称")
    parser.add_argument("--url", required=False, help="师资页面 URL")
    parser.add_argument("--all-departments", action="store_true", help="抓取全部核心院系")
    args = parser.parse_args()

    if args.all_departments:
        for dept in ["自动化系", "计算机科学与技术系", "电子工程系"]:
            crawl(dept, "")
    else:
        crawl(args.department, args.url or "")


if __name__ == "__main__":
    main()
