“文泉学堂”PDF下载
====================

[文泉学堂](https://lib-nuanxin.wqxuetang.com/)

1. 安装 requirements.txt 里的依赖
2. 找到你要的书，看地址栏的数字为 id
3. 运行 `python3 crawl_wqxt.py <id>`

若一直出现 not loaded（第二遍还是），请尝试重新运行，已下载的图片不会重新下载。

若需要清理缓存，请删除 wqxt.db 或自行更改其内容（SQLite 数据库）。

若需要登录，请自行在 `crawl_wqxt.py` 的 HEADERS（36行）里加 Cookie 等内容。

