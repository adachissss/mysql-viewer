# MySQL Viewer

一个基于 Flask 的轻量级 MySQL 可视化工具，支持数据库/表浏览、结构查看、分页数据查看，以及常见管理操作。

## 功能特性

- 连接 MySQL 并获取数据库列表
- 查看数据库中的表列表
- 展开表查看字段结构（Structure）
- 分页查看表数据（Data）
- 分页支持固定每页数量（50/100/200，默认 50）
- 总条数采用折中策略：首屏或手动触发时做精确统计，翻页默认不重复执行 COUNT(*)
- 右键数据库：删除数据库
- 右键表：重命名表、清空表、删除表
- 右键数据行：删除指定行（基于主键）
- 双击单元格：表格内联编辑，按 Enter 提交，Esc 取消
- 连接信息本地缓存（localStorage）
- 前端已拆分为 HTML / CSS / JS（便于维护）

## 项目结构

```text
mysql-viewer/
├── app.py
├── requirements.txt
├── templates/
│   └── index.html
└── static/
    ├── style.css
    └── app.js
```

## 环境要求

- Python 3.8+
- MySQL 5.7+ / 8.0+

## 安装与启动

1. 创建虚拟环境（可选）

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 启动服务

```bash
python app.py
```

4. 打开浏览器访问

```text
http://127.0.0.1:5050
```

## 使用说明

1. 在左侧输入 MySQL 连接信息并点击 Connect。
2. 选择数据库后，右侧展示表列表。
3. 点击表头展开，默认进入 Structure 标签。
4. 切换 Data 标签查看分页数据。
    - 可切换每页数量（默认 50）
    - 可按需点击 Count total 触发精确总数统计
5. 双击任意数据单元格可直接编辑：
   - Enter：提交更新
   - Esc：取消编辑
6. 右键可进行数据库、表、行级操作。

## 安全与限制说明

- 涉及删除/清空/更新的操作都直接作用于真实数据库，请谨慎使用。
- 行级更新/删除依赖主键定位。没有主键的表，前端会阻止精确行操作。
- 标识符（库名、表名、列名）在后端做了基础转义处理；值参数使用参数化执行。

## 后端接口一览

- `POST /api/connect`：测试连接
- `POST /api/databases`：获取数据库列表
- `POST /api/tables`：获取表列表
- `POST /api/table_schema`：获取表结构
- `POST /api/table_data`：获取表数据（分页 + 主键信息）
- `POST /api/drop_database`：删除数据库
- `POST /api/drop_table`：删除表
- `POST /api/rename_table`：重命名表
- `POST /api/truncate_table`：清空表
- `POST /api/update_cell`：更新单元格
- `POST /api/delete_row`：删除指定行

## 常见问题

### 大表分页感觉慢

- 当前分页默认优先保证翻页速度：翻页请求默认不执行 `COUNT(*)`
- 首屏或点击 `Count total` 时才进行精确总数统计
- 若仍然较慢，优先排查索引、SQL 与网络延迟，再考虑引入连接池

### 连接失败

- 检查 host/port/user/password 是否正确
- 确认 MySQL 服务已启动
- 确认账号有对应库/表的访问与修改权限

### 行删除或单元格更新失败

- 先确认该表存在主键
- 若主键为复合主键，系统会同时使用多个主键列进行定位

## License

仅用于学习与内部工具用途，请根据你的实际场景自行补充许可证。
